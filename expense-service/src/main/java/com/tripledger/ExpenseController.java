package com.tripledger;

import com.fasterxml.jackson.databind.*;
import com.tripledger.common.*;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.math.BigDecimal;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
public class ExpenseController {
  private final JdbcTemplate db;
  private final ObjectMapper json;
  private final Internal internal;
  private final String identity, policy;

  public ExpenseController(
      JdbcTemplate d,
      ObjectMapper j,
      Internal i,
      @Value("${trip.identity-url}") String identity,
      @Value("${trip.policy-url}") String policy) {
    db = d;
    json = j;
    internal = i;
    this.identity = identity;
    this.policy = policy;
  }

  public record Line(
      @NotBlank @Size(max = 60) String lineId,
      @NotNull LocalDate date,
      @NotBlank @Size(max = 60) String category,
      @NotBlank @Size(max = 160) String merchant,
      @DecimalMin("0.00") @Digits(integer = 12, fraction = 6) @NotNull BigDecimal amount,
      @Pattern(regexp = "[A-Z]{3}") @NotNull String currency,
      @NotBlank @Size(max = 2000) String description,
      UUID receiptId,
      @Min(1) @Max(365) Integer hotelNights,
      @Min(1) @Max(1000) Integer attendeeCount,
      Boolean clientDinner,
      @DecimalMin("0.00") @Digits(integer = 12, fraction = 6) BigDecimal alcoholAmount) {}

  public record Draft(
      @NotBlank @Size(max = 160) String title,
      @NotBlank @Size(max = 2000) String purpose,
      @NotBlank @Size(max = 200) String destination,
      @NotNull LocalDate startDate,
      @NotNull LocalDate endDate,
      @Pattern(regexp = "[A-Z]{3}") @NotNull String baseCurrency,
      @NotEmpty @Size(max = 50) List<@Valid Line> lines,
      int rowVersion) {}

  public record Version(int rowVersion) {}

  public record Decision(
      int rowVersion,
      @Pattern(regexp = "APPROVE|REJECT|CLARIFY") @NotNull String action,
      @NotBlank @Size(max = 4000) String reason,
      @DecimalMin("0.00") @Digits(integer = 14, fraction = 2) BigDecimal approvedAmount) {}

  public record Assignment(int rowVersion, @NotNull UUID managerId) {}

  String encode(Object value) {
    try {
      return json.writeValueAsString(value);
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }

  Map<String, Object> convert(Map<String, Object> row) {
    for (String key : List.of("payload", "ai_result", "decision", "result")) {
      Object v = row.get(key);
      if (v != null)
        try {
          row.put(key, json.readTree(v.toString()));
        } catch (Exception e) {
          throw new IllegalStateException(e);
        }
    }
    return row;
  }

  Map<String, Object> report(UUID id, boolean lock) {
    var rows =
        db.queryForList("select * from reports where id=?" + (lock ? " for update" : ""), id);
    if (rows.isEmpty()) throw ApiError.missing();
    return convert(rows.get(0));
  }

  boolean owner(Actor a, Map<String, Object> r) {
    return a.id().equals(r.get("employee_id").toString());
  }

  void access(Actor a, Map<String, Object> r) {
    if (!a.admin()
        && !owner(a, r)
        && !(a.manager() && a.id().equals(String.valueOf(r.get("manager_id")))))
      throw ApiError.forbidden();
  }

  void edit(Actor a, Map<String, Object> r, int version) {
    if (!owner(a, r)) throw ApiError.forbidden();
    version(r, version);
    if (!Set.of("DRAFT", "CLARIFICATION").contains(r.get("status").toString()))
      throw ApiError.conflict("Only draft or clarification reports can be edited");
  }

  void version(Map<String, Object> r, int version) {
    if (((Number) r.get("row_version")).intValue() != version)
      throw ApiError.conflict("Report changed. Refresh and try again.");
  }

  void manager(Actor a, Map<String, Object> r) {
    if (!a.manager() || !a.id().equals(String.valueOf(r.get("manager_id"))) || owner(a, r))
      throw ApiError.forbidden();
  }

  void validate(Draft d, UUID reportId) {
    if (d.endDate().isBefore(d.startDate())) throw ApiError.bad("Trip end must follow trip start");
    Set<String> ids = new HashSet<>();
    for (Line l : d.lines()) {
      if (!ids.add(l.lineId())) throw ApiError.bad("Expense line IDs must be unique");
      if (l.receiptId() != null
          && (reportId == null
              || db.queryForObject(
                      "select count(*) from receipts where id=? and report_id=?",
                      Integer.class,
                      l.receiptId(),
                      reportId)
                  == 0)) throw ApiError.bad("Receipt does not belong to this report");
    }
  }

  void audit(UUID id, String actor, String action, String note) {
    db.update(
        "insert into audit(report_id,actor_id,action,note)values(?,?,?,?)",
        id,
        actor,
        action,
        note);
  }

  @GetMapping("/api/reports")
  public List<Map<String, Object>> list(HttpServletRequest req) {
    Actor a = Security.actor(req);
    List<Map<String, Object>> rows;
    if (a.admin())
      rows = db.queryForList("select * from reports order by updated_at desc limit 500");
    else if (a.manager())
      rows =
          db.queryForList(
              "select * from reports where employee_id=? or manager_id=? order by updated_at desc"
                  + " limit 500",
              UUID.fromString(a.id()),
              UUID.fromString(a.id()));
    else
      rows =
          db.queryForList(
              "select * from reports where employee_id=? order by updated_at desc limit 500",
              UUID.fromString(a.id()));
    return rows.stream().map(this::convert).toList();
  }

  @GetMapping("/api/reports/{id}")
  public Map<String, Object> get(HttpServletRequest req, @PathVariable UUID id) {
    var r = report(id, false);
    access(Security.actor(req), r);
    r.put("audit", db.queryForList("select * from audit where report_id=? order by id", id));
    r.put(
        "reviews",
        db
            .queryForList(
                "select * from review_jobs where report_id=? order by created_at desc", id)
            .stream()
            .map(this::convert)
            .toList());
    r.put(
        "receipts",
        db.queryForList("select id,name,mime,sha256 from receipts where report_id=?", id));
    r.put(
        "revisions",
        db.queryForList("select * from revisions where report_id=? order by revision", id).stream()
            .map(this::convert)
            .toList());
    return r;
  }

  @PostMapping("/api/reports")
  @Transactional
  public Map<String, Object> create(HttpServletRequest req, @Valid @RequestBody Draft d) {
    Actor a = Security.actor(req);
    if (a.admin()) throw ApiError.forbidden();
    validate(d, null);
    UUID id = UUID.randomUUID();
    db.update(
        "insert into reports(id,employee_id,employee_name,title,payload) values(?,?,?,?,?::jsonb)",
        id,
        UUID.fromString(a.id()),
        a.name(),
        d.title(),
        encode(d));
    audit(id, a.id(), "CREATED", "");
    return report(id, false);
  }

  @PutMapping("/api/reports/{id}")
  @Transactional
  public Map<String, Object> update(
      HttpServletRequest req, @PathVariable UUID id, @Valid @RequestBody Draft d) {
    Actor a = Security.actor(req);
    var r = report(id, true);
    edit(a, r, d.rowVersion());
    validate(d, id);
    db.update(
        "update reports set title=?,payload=?::jsonb,row_version=row_version+1,updated_at=now()"
            + " where id=?",
        d.title(),
        encode(d),
        id);
    audit(id, a.id(), "DRAFT_SAVED", "");
    return report(id, false);
  }

  void enqueue(UUID id, int revision) {
    UUID job = UUID.randomUUID();
    db.update("insert into review_jobs(id,report_id,revision) values(?,?,?)", job, id, revision);
    db.update(
        "insert into outbox(id,event)values(?,?::jsonb)",
        job,
        encode(Map.of("jobId", job, "reportId", id, "revision", revision)));
    db.update(
        "update reports set"
            + " job_id=?,ai_status='PENDING',ai_result=null,row_version=row_version+1,updated_at=now()"
            + " where id=?",
        job,
        id);
  }

  @PostMapping("/api/reports/{id}/submit")
  @Transactional
  public Map<String, Object> submit(
      HttpServletRequest req, @PathVariable UUID id, @RequestBody Version v) {
    Actor a = Security.actor(req);
    var r = report(id, true);
    edit(a, r, v.rowVersion());
    Actor employee =
        internal
            .http
            .get()
            .uri(identity + "/internal/users/" + a.id())
            .retrieve()
            .body(Actor.class);
    if (employee == null || employee.managerId() == null)
      throw ApiError.bad("Ask an administrator to assign your manager first");
    Actor m =
        internal
            .http
            .get()
            .uri(identity + "/internal/users/" + employee.managerId())
            .retrieve()
            .body(Actor.class);
    if (m == null || !m.active() || !m.manager() || m.id().equals(a.id()))
      throw ApiError.bad("Assigned manager is unavailable");
    JsonNode p =
        internal
            .http
            .get()
            .uri(policy + "/internal/policies/active")
            .retrieve()
            .body(JsonNode.class);
    UUID pid = UUID.fromString(p.path("id").asText());
    int revision = ((Number) r.get("revision")).intValue() + 1;
    db.update(
        "insert into revisions(report_id,revision,payload,policy_id) values(?,?,?::jsonb,?)",
        id,
        revision,
        encode(r.get("payload")),
        pid);
    db.update(
        "update reports set status='SUBMITTED',revision=?,policy_id=?,manager_id=?,decision=null"
            + " where id=?",
        revision,
        pid,
        UUID.fromString(m.id()),
        id);
    enqueue(id, revision);
    audit(id, a.id(), "SUBMITTED", "Revision " + revision);
    return report(id, false);
  }

  @PostMapping("/api/reports/{id}/decision")
  @Transactional
  public Map<String, Object> decision(
      HttpServletRequest req, @PathVariable UUID id, @Valid @RequestBody Decision d) {
    Actor a = Security.actor(req);
    var r = report(id, true);
    manager(a, r);
    version(r, d.rowVersion());
    if (!r.get("status").equals("AWAITING_REVIEW"))
      throw ApiError.conflict("Report is not awaiting a manager decision");
    if (d.action().equals("APPROVE") && d.approvedAmount() == null)
      throw ApiError.bad("Enter the approved amount in the report currency");
    if (d.action().equals("APPROVE")) {
      BigDecimal claimed = null;
      JsonNode payload = (JsonNode) r.get("payload");
      JsonNode ai = (JsonNode) r.get("ai_result");
      if (ai != null && ai.hasNonNull("claimedTotal"))
        claimed = new BigDecimal(ai.path("claimedTotal").asText());
      else {
        boolean same = true;
        BigDecimal sum = BigDecimal.ZERO;
        for (JsonNode line : payload.path("lines")) {
          same &= line.path("currency").asText().equals(payload.path("baseCurrency").asText());
          sum = sum.add(new BigDecimal(line.path("amount").asText()));
        }
        if (same) claimed = sum.setScale(2, java.math.RoundingMode.HALF_UP);
      }
      if (claimed != null && d.approvedAmount().compareTo(claimed) > 0)
        throw ApiError.bad("Approved amount cannot exceed the claimed total");
    }
    String status =
        switch (d.action()) {
          case "APPROVE" -> "APPROVED";
          case "REJECT" -> "REJECTED";
          default -> "CLARIFICATION";
        };
    Map<String, Object> value = new LinkedHashMap<>();
    value.put("action", d.action());
    value.put("reason", d.reason());
    value.put(
        "approvedAmount", d.approvedAmount() == null ? null : d.approvedAmount().toPlainString());
    value.put("currency", ((JsonNode) r.get("payload")).path("baseCurrency").asText());
    value.put("managerId", a.id());
    value.put("at", java.time.Instant.now().toString());
    db.update(
        "update reports set status=?,decision=?::jsonb,row_version=row_version+1,updated_at=now()"
            + " where id=?",
        status,
        encode(value),
        id);
    audit(id, a.id(), status, d.reason());
    return report(id, false);
  }

  @PostMapping("/api/reports/{id}/retry")
  @Transactional
  public Map<String, Object> retry(
      HttpServletRequest req, @PathVariable UUID id, @RequestBody Version v) {
    Actor a = Security.actor(req);
    var r = report(id, true);
    if (!a.admin()) manager(a, r);
    version(r, v.rowVersion());
    if (!r.get("ai_status").equals("FAILED") || !r.get("status").equals("AWAITING_REVIEW"))
      throw ApiError.conflict("Only failed reviews can be retried");
    db.update("update reports set status='SUBMITTED' where id=?", id);
    enqueue(id, ((Number) r.get("revision")).intValue());
    audit(id, a.id(), "AI_RETRY", "");
    return report(id, false);
  }

  @PostMapping("/api/reports/{id}/assign")
  @Transactional
  public Map<String, Object> assign(
      HttpServletRequest req, @PathVariable UUID id, @Valid @RequestBody Assignment v) {
    Actor a = Security.actor(req);
    a.require("ADMIN");
    var r = report(id, true);
    version(r, v.rowVersion());
    if (Set.of("APPROVED", "REJECTED").contains(r.get("status")))
      throw ApiError.conflict("Final reports cannot be reassigned");
    Actor m =
        internal
            .http
            .get()
            .uri(identity + "/internal/users/" + v.managerId())
            .retrieve()
            .body(Actor.class);
    if (m == null || !m.active() || !m.manager() || m.id().equals(r.get("employee_id").toString()))
      throw ApiError.bad("Choose a different active manager");
    db.update(
        "update reports set manager_id=?,row_version=row_version+1,updated_at=now() where id=?",
        v.managerId(),
        id);
    audit(id, a.id(), "REASSIGNED", m.name());
    return report(id, false);
  }

  @PostMapping("/api/reports/{id}/receipts")
  @Transactional
  public Map<String, Object> upload(
      HttpServletRequest req, @PathVariable UUID id, @RequestParam("file") MultipartFile file)
      throws Exception {
    Actor a = Security.actor(req);
    var r = report(id, true);
    edit(a, r, ((Number) r.get("row_version")).intValue());
    if (file.isEmpty() || file.getSize() > 8 * 1024 * 1024)
      throw ApiError.bad("Choose a receipt under 8 MB");
    if (db.queryForObject("select count(*) from receipts where report_id=?", Integer.class, id)
        >= 100) throw ApiError.bad("Maximum 100 receipt uploads per report");
    byte[] data = file.getBytes();
    String mime = null;
    if (data.length >= 8
        && data[0] == (byte) 0x89
        && data[1] == 'P'
        && data[2] == 'N'
        && data[3] == 'G') mime = "image/png";
    if (data.length >= 3
        && data[0] == (byte) 0xff
        && data[1] == (byte) 0xd8
        && data[2] == (byte) 0xff) mime = "image/jpeg";
    if (mime == null) throw ApiError.bad("Use a PNG or JPEG receipt");
    UUID rid = UUID.randomUUID();
    String name =
        Optional.ofNullable(file.getOriginalFilename())
            .orElse("receipt")
            .replaceAll("[^a-zA-Z0-9._ -]", "_");
    if (name.length() > 100) name = name.substring(name.length() - 100);
    db.update(
        "insert into receipts(id,report_id,name,mime,sha256,data)values(?,?,?,?,?,?)",
        rid,
        id,
        name,
        mime,
        HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data)),
        data);
    audit(id, a.id(), "RECEIPT_UPLOADED", rid.toString());
    return Map.of("id", rid, "name", name);
  }

  ResponseEntity<byte[]> receipt(UUID id, UUID receiptId) {
    var rows = db.queryForList("select * from receipts where id=? and report_id=?", receiptId, id);
    if (rows.isEmpty()) throw ApiError.missing();
    var row = rows.get(0);
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .header("X-Content-Type-Options", "nosniff")
        .header(
            "Content-Disposition",
            "attachment; filename=receipt-"
                + receiptId
                + (row.get("mime").equals("image/png") ? ".png" : ".jpg"))
        .contentType(MediaType.parseMediaType(row.get("mime").toString()))
        .body((byte[]) row.get("data"));
  }

  @GetMapping("/api/reports/{id}/receipts/{receiptId}")
  public ResponseEntity<byte[]> download(
      HttpServletRequest req, @PathVariable UUID id, @PathVariable UUID receiptId) {
    access(Security.actor(req), report(id, false));
    return receipt(id, receiptId);
  }

  @GetMapping("/internal/jobs/{jobId}")
  public Map<String, Object> job(@PathVariable UUID jobId) {
    var rows =
        db.queryForList(
            "select j.*,r.payload,r.policy_id from review_jobs j join revisions r on"
                + " r.report_id=j.report_id and r.revision=j.revision where j.id=?",
            jobId);
    if (rows.isEmpty()) throw ApiError.missing();
    var result = convert(rows.get(0));
    UUID reportId = (UUID) result.get("report_id");
    result.put(
        "receipts",
        db.queryForList("select id,sha256,mime,name from receipts where report_id=?", reportId));
    return result;
  }

  @GetMapping("/internal/jobs/{jobId}/receipts/{receiptId}")
  public ResponseEntity<byte[]> internalReceipt(
      @PathVariable UUID jobId, @PathVariable UUID receiptId) {
    var j = job(jobId);
    JsonNode payload = (JsonNode) j.get("payload");
    boolean allowed = false;
    for (JsonNode l : payload.path("lines"))
      if (l.path("receiptId").asText().equals(receiptId.toString())) allowed = true;
    if (!allowed) throw ApiError.forbidden();
    return receipt((UUID) j.get("report_id"), receiptId);
  }

  @PostMapping("/internal/jobs/{jobId}/started")
  @Transactional
  public Map<String, Boolean> started(@PathVariable UUID jobId) {
    var j = job(jobId);
    db.update("update review_jobs set status='RUNNING' where id=? and status='PENDING'", jobId);
    db.update(
        "update reports set ai_status='RUNNING' where job_id=? and ai_status='PENDING'", jobId);
    return Map.of("ok", true);
  }

  @PostMapping("/internal/jobs/{jobId}/result")
  @Transactional
  public Map<String, Boolean> result(@PathVariable UUID jobId, @RequestBody JsonNode result) {
    if (!Set.of("COMPLETED", "FAILED").contains(result.path("status").asText()))
      throw ApiError.bad("Invalid review status");
    var rows = db.queryForList("select * from review_jobs where id=? for update", jobId);
    if (rows.isEmpty()) throw ApiError.missing();
    if (Set.of("COMPLETED", "FAILED").contains(rows.get(0).get("status")))
      return Map.of("ok", true);
    db.update(
        "update review_jobs set status=?,result=?::jsonb,completed_at=now() where id=?",
        result.path("status").asText(),
        encode(result),
        jobId);
    db.update(
        "update reports set"
            + " ai_status=?,ai_result=?::jsonb,status='AWAITING_REVIEW',row_version=row_version+1,updated_at=now()"
            + " where job_id=? and status='SUBMITTED'",
        result.path("status").asText(),
        encode(result),
        jobId);
    audit((UUID) rows.get(0).get("report_id"), "AI", result.path("status").asText(), "");
    return Map.of("ok", true);
  }

  @GetMapping("/internal/jobs/{jobId}/duplicates")
  public List<Map<String, Object>> duplicates(@PathVariable UUID jobId) {
    var j = job(jobId);
    return db.queryForList(
        "select distinct old.report_id,old.id as receipt_id,old.sha256 from receipts current join"
            + " receipts old on old.sha256=current.sha256 and old.report_id<>current.report_id join"
            + " reports r on r.id=old.report_id where current.report_id=? and r.status in"
            + " ('SUBMITTED','AWAITING_REVIEW','APPROVED')",
        j.get("report_id"));
  }
}
