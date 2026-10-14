package com.tripledger.common;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.filter.OncePerRequestFilter;

@Configuration
public class Security {
  @Bean
  SecurityFilterChain chain(
      HttpSecurity http,
      Internal internal,
      @Value("${trip.identity-url}") String identity,
      @Value("${trip.service-key}") String key,
      @Value("${trip.service-name}") String service)
      throws Exception {
    http.csrf(c -> c.disable())
        .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS));
    http.authorizeHttpRequests(a -> a.anyRequest().permitAll());
    http.addFilterBefore(
        new OncePerRequestFilter() {
          protected void doFilterInternal(
              HttpServletRequest req, HttpServletResponse res, FilterChain chain)
              throws ServletException, IOException {
            String path = req.getRequestURI();
            if (service.equals("api-gateway")
                || path.equals("/actuator/health")
                || path.equals("/error")
                || path.equals("/api/auth/login")) {
              chain.doFilter(req, res);
              return;
            }
            if (path.startsWith("/internal/")) {
              String supplied = req.getHeader("X-Service-Key");
              if (supplied == null
                  || !MessageDigest.isEqual(
                      key.getBytes(StandardCharsets.UTF_8),
                      supplied.getBytes(StandardCharsets.UTF_8))) {
                res.sendError(401);
                return;
              }
              chain.doFilter(req, res);
              return;
            }
            String auth = req.getHeader("Authorization");
            if (auth == null || !auth.startsWith("Bearer ")) {
              res.sendError(401);
              return;
            }
            try {
              Actor actor =
                  internal
                      .http
                      .post()
                      .uri(identity + "/internal/session")
                      .header("Authorization", auth)
                      .retrieve()
                      .body(Actor.class);
              if (actor == null || !actor.active()) {
                res.sendError(401);
                return;
              }
              SecurityContextHolder.getContext()
                  .setAuthentication(
                      new UsernamePasswordAuthenticationToken(
                          actor,
                          null,
                          List.of(new SimpleGrantedAuthority("ROLE_" + actor.role()))));
              req.setAttribute("actor", actor);
            } catch (org.springframework.web.client.HttpClientErrorException e) {
              res.sendError(401);
              return;
            } catch (Exception e) {
              res.sendError(503);
              return;
            }
            try {
              chain.doFilter(req, res);
            } finally {
              SecurityContextHolder.clearContext();
            }
          }
        },
        UsernamePasswordAuthenticationFilter.class);
    return http.build();
  }

  public static Actor actor(HttpServletRequest req) {
    return (Actor) req.getAttribute("actor");
  }
}
