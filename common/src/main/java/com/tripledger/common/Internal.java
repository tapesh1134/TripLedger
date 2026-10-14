package com.tripledger.common;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class Internal {
  public final RestClient http;

  public Internal(@Value("${trip.service-key}") String key) {
    if (key.length() < 32)
      throw new IllegalStateException("SERVICE_KEY must contain at least 32 characters");
    var factory = new SimpleClientHttpRequestFactory();
    factory.setConnectTimeout(5000);
    factory.setReadTimeout(180000);
    http = RestClient.builder().requestFactory(factory).defaultHeader("X-Service-Key", key).build();
  }
}
