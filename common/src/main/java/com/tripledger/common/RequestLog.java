package com.tripledger.common;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class RequestLog extends OncePerRequestFilter {
  @Override
  protected void doFilterInternal(
      HttpServletRequest request, HttpServletResponse response, FilterChain chain)
      throws ServletException, IOException {
    String id = request.getHeader("X-Request-ID");
    if (id == null || !id.matches("[a-zA-Z0-9-]{1,64}")) id = UUID.randomUUID().toString();
    response.setHeader("X-Request-ID", id);
    long start = System.nanoTime();
    try {
      chain.doFilter(request, response);
    } finally {
      LoggerFactory.getLogger(RequestLog.class)
          .info(
              "request_id={} method={} path={} status={} duration_ms={}",
              id,
              request.getMethod(),
              request.getRequestURI(),
              response.getStatus(),
              (System.nanoTime() - start) / 1000000);
    }
  }
}
