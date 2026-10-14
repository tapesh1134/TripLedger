package com.tripledger;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class LoginLimit extends OncePerRequestFilter {
  private record Window(long minute, int count) {}

  private final ConcurrentHashMap<String, Window> windows = new ConcurrentHashMap<>();

  @Override
  protected void doFilterInternal(
      HttpServletRequest req, HttpServletResponse res, FilterChain chain)
      throws ServletException, IOException {
    if (req.getRequestURI().equals("/api/auth/login")) {
      long minute = System.currentTimeMillis() / 60000;
      if (windows.size() > 10000) windows.entrySet().removeIf(e -> e.getValue().minute() < minute);
      Window window =
          windows.compute(
              req.getRemoteAddr(),
              (key, old) ->
                  new Window(minute, old != null && old.minute() == minute ? old.count() + 1 : 1));
      if (window.count() > 20) {
        res.setStatus(429);
        res.setHeader("Retry-After", "60");
        res.setContentType("application/json");
        res.getWriter()
            .write("{\"error\":\"Too many sign-in attempts. Wait a minute and retry.\"}");
        return;
      }
    }
    chain.doFilter(req, res);
  }
}
