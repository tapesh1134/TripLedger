package com.tripledger;

import com.tripledger.common.*;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

@RestController
public class IdentityController implements ApplicationRunner {
  private final JdbcTemplate db;
  private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder(12);
  private final String adminEmail, adminPassword;

  public IdentityController(
      JdbcTemplate db,
      @Value("${trip.admin-email}") String email,
      @Value("${trip.admin-password}") String password) {
    this.db = db;
    adminEmail = email;
    adminPassword = password;
  }

  public void run(ApplicationArguments args) {
    if (db.queryForObject("select count(*) from people", Integer.class) == 0) {
      if (adminPassword.length() < 12)
        throw new IllegalStateException("Bootstrap password must contain at least 12 characters");
      db.update(
          "insert into people(id,email,name,password_hash,role) values(?,?,?,?,?)",
          UUID.randomUUID(),
          adminEmail.toLowerCase(),
          "Administrator",
          encoder.encode(adminPassword),
          "ADMIN");
    }
  }

  public record Password(
      @NotBlank String currentPassword, @NotNull @Size(min = 12, max = 72) String newPassword) {}

  public record Login(@Email @NotBlank String email, @NotBlank String password) {}

  public record UserInput(
      @Email @NotBlank String email,
      @NotBlank @Size(max = 100) String name,
      @Size(min = 12, max = 72) String password,
      @Pattern(regexp = "ADMIN|MANAGER|EMPLOYEE") @NotNull String role,
      UUID managerId,
      boolean active) {}

  private Actor actor(Map<String, Object> row) {
    return new Actor(
        row.get("id").toString(),
        row.get("email").toString(),
        row.get("name").toString(),
        row.get("role").toString(),
        row.get("manager_id") == null ? null : row.get("manager_id").toString(),
        (Boolean) row.get("active"));
  }

  private Map<String, Object> row(UUID id) {
    var rows = db.queryForList("select * from people where id=?", id);
    if (rows.isEmpty()) throw ApiError.missing();
    return rows.get(0);
  }

  static String hash(String token) {
    try {
      return HexFormat.of()
          .formatHex(
              MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8)));
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }

  @PostMapping("/api/auth/login")
  public Map<String, Object> login(@Valid @RequestBody Login input) {
    var rows =
        db.queryForList(
            "select * from people where email=? and active=true",
            input.email().trim().toLowerCase());
    if (rows.isEmpty()
        || !encoder.matches(input.password(), rows.get(0).get("password_hash").toString()))
      throw new ApiError(HttpStatus.UNAUTHORIZED, "Invalid email or password");
    byte[] bytes = new byte[32];
    new SecureRandom().nextBytes(bytes);
    String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    Actor a = actor(rows.get(0));
    db.update(
        "insert into sessions values(?,?,now()+interval '8 hours')",
        hash(token),
        UUID.fromString(a.id()));
    return Map.of("token", token, "user", a, "expiresIn", 28800);
  }

  @PostMapping("/internal/session")
  public Actor session(@RequestHeader("Authorization") String auth) {
    String token = auth.replaceFirst("^Bearer ", "");
    var rows =
        db.queryForList(
            "select p.* from people p join sessions s on s.user_id=p.id where s.token_hash=? and"
                + " s.expires_at>now() and p.active",
            hash(token));
    if (rows.isEmpty()) throw new ApiError(HttpStatus.UNAUTHORIZED, "Session expired");
    return actor(rows.get(0));
  }

  @PostMapping("/api/auth/password")
  @Transactional
  public Map<String, Boolean> password(HttpServletRequest req, @Valid @RequestBody Password input) {
    Actor a = Security.actor(req);
    UUID id = UUID.fromString(a.id());
    var current = row(id);
    if (!encoder.matches(input.currentPassword(), current.get("password_hash").toString()))
      throw ApiError.bad("Current password is incorrect");
    db.update(
        "update people set password_hash=? where id=?", encoder.encode(input.newPassword()), id);
    db.update("delete from sessions where user_id=?", id);
    audit(a, "PASSWORD_CHANGED", id);
    return Map.of("ok", true);
  }

  @GetMapping("/api/auth/me")
  public Actor me(HttpServletRequest req) {
    return Security.actor(req);
  }

  @PostMapping("/api/auth/logout")
  public Map<String, Boolean> logout(@RequestHeader("Authorization") String token) {
    db.update("delete from sessions where token_hash=?", hash(token.substring(7)));
    return Map.of("ok", true);
  }

  @GetMapping("/api/users")
  public List<Actor> users(HttpServletRequest req) {
    Security.actor(req).require("ADMIN");
    return db.queryForList("select * from people order by created_at").stream()
        .map(this::actor)
        .toList();
  }

  @GetMapping("/internal/users/{id}")
  public Actor internalUser(@PathVariable UUID id) {
    return actor(row(id));
  }

  private void manager(UUID managerId, UUID self) {
    if (managerId != null) {
      Actor m = actor(row(managerId));
      if (!m.active() || !m.manager() || managerId.equals(self))
        throw ApiError.bad("Choose a different active manager");
    }
  }

  @PostMapping("/api/users")
  @Transactional
  public Actor create(HttpServletRequest req, @Valid @RequestBody UserInput input) {
    Actor a = Security.actor(req);
    a.require("ADMIN");
    if (input.password() == null) throw ApiError.bad("Password is required");
    UUID id = UUID.randomUUID();
    manager(input.managerId(), id);
    if (db.queryForObject(
            "select count(*) from people where email=?",
            Integer.class,
            input.email().trim().toLowerCase())
        > 0) throw ApiError.conflict("Email already exists");
    db.update(
        "insert into people(id,email,name,password_hash,role,manager_id,active)"
            + " values(?,?,?,?,?,?,?)",
        id,
        input.email().trim().toLowerCase(),
        input.name(),
        encoder.encode(input.password()),
        input.role(),
        input.managerId(),
        input.active());
    audit(a, "CREATE_USER", id);
    return actor(row(id));
  }

  @PutMapping("/api/users/{id}")
  @Transactional
  public Actor update(
      HttpServletRequest req, @PathVariable UUID id, @Valid @RequestBody UserInput input) {
    Actor a = Security.actor(req);
    a.require("ADMIN");
    row(id);
    if (a.id().equals(id.toString()) && (!input.active() || !input.role().equals("ADMIN")))
      throw ApiError.bad("You cannot remove your own administrator access");
    manager(input.managerId(), id);
    if (db.queryForObject("select count(*) from people where manager_id=?", Integer.class, id) > 0
        && (!input.role().equals("MANAGER") || !input.active()))
      throw ApiError.conflict("Reassign this manager's employees first");
    db.update(
        "update people set email=?,name=?,role=?,manager_id=?,active=? where id=?",
        input.email().trim().toLowerCase(),
        input.name(),
        input.role(),
        input.managerId(),
        input.active(),
        id);
    if (input.password() != null)
      db.update(
          "update people set password_hash=? where id=?", encoder.encode(input.password()), id);
    db.update("delete from sessions where user_id=?", id);
    audit(a, "UPDATE_USER", id);
    return actor(row(id));
  }

  void audit(Actor a, String action, UUID subject) {
    db.update(
        "insert into identity_audit(actor_id,action,subject_id) values(?,?,?)",
        UUID.fromString(a.id()),
        action,
        subject);
  }

  @GetMapping("/api/users/audit")
  public List<Map<String, Object>> audit(HttpServletRequest req) {
    Security.actor(req).require("ADMIN");
    return db.queryForList("select * from identity_audit order by id desc limit 200");
  }
}
