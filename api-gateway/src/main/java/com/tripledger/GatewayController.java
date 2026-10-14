package com.tripledger;

import com.tripledger.common.*;
import jakarta.servlet.http.*;
import java.io.*;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

@RestController
public class GatewayController {
  private final HttpClient client =
      HttpClient.newBuilder()
          .connectTimeout(Duration.ofSeconds(5))
          .followRedirects(HttpClient.Redirect.NEVER)
          .build();
  private final String identity, expense, policy;

  public GatewayController(
      @Value("${trip.identity-url}") String i,
      @Value("${trip.expense-url}") String e,
      @Value("${trip.policy-url}") String p) {
    identity = i;
    expense = e;
    policy = p;
  }

  @RequestMapping("/api/**")
  public void route(HttpServletRequest req, HttpServletResponse res) throws Exception {
    String path = req.getRequestURI();
    String target;
    if (path.startsWith("/api/auth/")
        || path.equals("/api/users")
        || path.startsWith("/api/users/")) target = identity;
    else if (path.equals("/api/reports") || path.startsWith("/api/reports/")) target = expense;
    else if (path.equals("/api/policies") || path.startsWith("/api/policies/")) target = policy;
    else {
      res.sendError(404);
      return;
    }
    if (!path.matches("/api/[a-zA-Z0-9/_-]+")
        || !Set.of("GET", "POST", "PUT", "DELETE").contains(req.getMethod())) {
      res.sendError(400);
      return;
    }
    byte[] body = req.getInputStream().readNBytes(10 * 1024 * 1024 + 1);
    if (body.length > 10 * 1024 * 1024) {
      res.sendError(413);
      return;
    }
    String requestId = UUID.randomUUID().toString();
    var request =
        HttpRequest.newBuilder(URI.create(target + path))
            .timeout(Duration.ofSeconds(180))
            .header("X-Request-ID", requestId);
    for (String header : List.of("Authorization", "Content-Type")) {
      String value = req.getHeader(header);
      if (value != null) request.header(header, value);
    }
    var response =
        client.send(
            request.method(req.getMethod(), HttpRequest.BodyPublishers.ofByteArray(body)).build(),
            HttpResponse.BodyHandlers.ofByteArray());
    res.setStatus(response.statusCode());
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Request-ID", requestId);
    res.setHeader("X-Content-Type-Options", "nosniff");
    for (String header : List.of("Content-Type", "Content-Disposition"))
      response.headers().firstValue(header).ifPresent(v -> res.setHeader(header, v));
    res.getOutputStream().write(response.body());
  }
}
