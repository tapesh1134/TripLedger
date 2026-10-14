package com.tripledger;

import com.fasterxml.jackson.databind.*;
import com.tripledger.common.*;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.math.BigDecimal;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.bind.annotation.*;

@RestController
public class PolicyController {
  private final JdbcTemplate db;
  private final ObjectMapper json;
  private final Internal internal;
  private final String ai;
  private final TransactionTemplate tx;

  public PolicyController(
      JdbcTemplate d,
      ObjectMapper j,
      Internal i,
      @Value("${trip.ai-url}") String a,
      org.springframework.transaction.PlatformTransactionManager manager) {
    db = d;
    json = j;
    internal = i;
    ai = a;
    tx = new TransactionTemplate(manager);
  }

  public record Rule(
      @NotBlank String category,
      @Pattern(regexp = "[A-Z]{3}") @NotNull String currency,
      @DecimalMin("0.00") @Digits(integer = 12, fraction = 2) @NotNull BigDecimal limit,
      @Pattern(regexp = "PER_EXPENSE|PER_NIGHT|PER_ATTENDEE") @NotNull String basis,
      boolean receiptRequired) {}

  public record PolicyInput(
      @NotBlank @Size(max = 160) String title,
      @NotBlank @Size(max = 100000) String content,
      @NotEmpty @Size(max = 100) List<@Valid Rule> rules) {}

  Map<String, Object> read(UUID id) {
    var rows = db.queryForList("select * from policies where id=?", id);
    if (rows.isEmpty()) throw ApiError.missing();
    return convert(rows.get(0));
  }

  Map<String, Object> convert(Map<String, Object> row) {
    try {
      row.put("rules", json.readTree(row.get("rules").toString()));
      return row;
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }

  @GetMapping("/api/policies")
  public List<Map<String, Object>> list() {
    return db.queryForList("select * from policies order by created_at desc").stream()
        .map(this::convert)
        .toList();
  }

  @PostMapping("/api/policies")
  public Map<String, Object> create(HttpServletRequest req, @Valid @RequestBody PolicyInput input)
      throws Exception {
    Actor a = Security.actor(req);
    a.require("ADMIN");
    Set<String> keys = new HashSet<>();
    for (Rule rule : input.rules())
      if (!keys.add(rule.category().toLowerCase() + ":" + rule.currency()))
        throw ApiError.bad("Only one rule per category and currency is allowed");
    UUID id = UUID.randomUUID();
    db.update(
        "insert into policies(id,title,content,rules,created_by)values(?,?,?,?::jsonb,?)",
        id,
        input.title(),
        input.content(),
        json.writeValueAsString(input.rules()),
        UUID.fromString(a.id()));
    return read(id);
  }

  @PostMapping("/api/policies/{id}/publish")
  public Map<String, Object> publish(HttpServletRequest req, @PathVariable UUID id) {
    Actor a = Security.actor(req);
    a.require("ADMIN");
    var policy = read(id);
    if (policy.get("status").equals("ACTIVE")) return policy;
    // Version content is immutable; repeated indexing is safe after a timeout or restart.
    try {
      internal.http.post().uri(ai + "/internal/index").body(policy).retrieve().toBodilessEntity();
    } catch (Exception e) {
      db.update(
          "update policies set error=? where id=?",
          "Indexing failed. Check AI service and embedding configuration.",
          id);
      throw ApiError.bad("Policy indexing failed. The current active policy is unchanged.");
    }
    tx.executeWithoutResult(
        status -> {
          db.execute("LOCK TABLE policies IN EXCLUSIVE MODE");
          db.update("update policies set status='ARCHIVED' where status='ACTIVE'");
          db.update("update policies set status='ACTIVE',error=null where id=?", id);
          db.update(
              "insert into policy_audit(policy_id,actor_id,action)values(?,?,'PUBLISH')",
              id,
              UUID.fromString(a.id()));
        });
    return read(id);
  }

  @GetMapping("/internal/policies/active")
  public Map<String, Object> active() {
    var rows = db.queryForList("select * from policies where status='ACTIVE'");
    if (rows.isEmpty())
      throw ApiError.conflict("An administrator must publish a policy before submission");
    return convert(rows.get(0));
  }

  @GetMapping("/internal/policies/{id}")
  public Map<String, Object> internal(@PathVariable UUID id) {
    return read(id);
  }
}
