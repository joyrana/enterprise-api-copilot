/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.enterprise.copilot.application.TokenService;
import io.enterprise.copilot.infrastructure.adapter.inbound.rest.PlatformRequestFilter;
import io.enterprise.copilot.infrastructure.adapter.inbound.rest.dto.ApiErrorResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtDecoders;
import org.springframework.security.oauth2.jwt.JwtIssuerValidator;
import org.springframework.security.oauth2.jwt.JwtTimestampValidator;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

/**
 * Stateless bearer-token security.
 *
 * <p>Tokens are HS256 with the algorithm pinned (no {@code none}, no algorithm confusion) and must
 * carry {@code iss}, {@code aud}, {@code sub}, {@code tenant_id}, {@code roles}, {@code iat} and
 * {@code exp} with a bounded lifetime. When {@code copilot.auth.oidc-issuer-uri} is set, tokens are
 * verified against that OIDC issuer's keys instead, with the same claim checks. The principal is
 * taken only from a verified token.
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

  private static final String[] PUBLIC_PATHS = {
    "/api/v1/health", "/api/v1/auth/dev-token", "/actuator/health/**", "/actuator/info"
  };

  @Value("${app.cors.allowed-origins:http://localhost:3000}")
  private List<String> allowedOrigins;

  /**
   * Builds the filter chain.
   *
   * @param http the security builder
   * @param entryPoint answers 401 in the platform error shape
   * @param decoder verifies bearer tokens
   * @return the chain
   * @throws Exception if the chain cannot be built
   */
  @Bean
  public SecurityFilterChain securityFilterChain(
      HttpSecurity http, AuthenticationEntryPoint entryPoint, JwtDecoder decoder) throws Exception {
    return http.csrf(AbstractHttpConfigurer::disable)
        .cors(cors -> cors.configurationSource(corsConfigurationSource()))
        .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
        .authorizeHttpRequests(
            auth -> auth.requestMatchers(PUBLIC_PATHS).permitAll().anyRequest().authenticated())
        .exceptionHandling(e -> e.authenticationEntryPoint(entryPoint))
        .oauth2ResourceServer(
            o -> o.jwt(j -> j.decoder(decoder)).authenticationEntryPoint(entryPoint))
        .build();
  }

  /**
   * Answers 401 with the platform error body and {@code WWW-Authenticate: Bearer}.
   *
   * @param mapper the JSON mapper
   * @return the entry point
   */
  @Bean
  public AuthenticationEntryPoint authenticationEntryPoint(ObjectMapper mapper) {
    return (request, response, exception) -> {
      response.setStatus(401);
      response.setHeader("WWW-Authenticate", "Bearer");
      response.setContentType(MediaType.APPLICATION_JSON_VALUE);
      mapper.writeValue(
          response.getOutputStream(),
          ApiErrorResponse.builder()
              .code("UNAUTHENTICATED")
              .message("invalid or expired token")
              .requestId(PlatformRequestFilter.idOf(request))
              .path(request.getRequestURI())
              .timestamp(Instant.now())
              .build());
    };
  }

  /**
   * The token verifier.
   *
   * @param properties the configuration
   * @return a decoder with pinned algorithm and the claim checks above
   */
  @Bean
  public JwtDecoder jwtDecoder(CopilotProperties properties) {
    CopilotProperties.Auth auth = properties.auth();
    JwtDecoder decoder;
    NimbusJwtDecoder local = null;
    if (auth.oidcIssuerUri() != null && !auth.oidcIssuerUri().isBlank()) {
      decoder = JwtDecoders.fromIssuerLocation(auth.oidcIssuerUri());
      if (decoder instanceof NimbusJwtDecoder nimbus) {
        nimbus.setJwtValidator(validators(auth, auth.oidcIssuerUri()));
      }
      return decoder;
    }
    if (auth.tokenKey() == null || auth.tokenKey().getBytes(StandardCharsets.UTF_8).length < 32) {
      throw new IllegalStateException("copilot.auth.token-key must be at least 32 bytes");
    }
    local =
        NimbusJwtDecoder.withSecretKey(
                new SecretKeySpec(auth.tokenKey().getBytes(StandardCharsets.UTF_8), "HmacSHA256"))
            .macAlgorithm(MacAlgorithm.HS256)
            .build();
    local.setJwtValidator(validators(auth, TokenService.ISSUER));
    return local;
  }

  private static OAuth2TokenValidator<Jwt> validators(CopilotProperties.Auth auth, String issuer) {
    OAuth2TokenValidator<Jwt> claims =
        jwt -> {
          boolean audienceOk =
              jwt.getAudience() != null && jwt.getAudience().contains(auth.audience());
          Object roles = jwt.getClaim("roles");
          boolean rolesOk =
              roles instanceof List<?> list && list.stream().allMatch(String.class::isInstance);
          String tenant = jwt.getClaimAsString("tenant_id");
          boolean present =
              jwt.getSubject() != null
                  && tenant != null
                  && !tenant.isBlank()
                  && jwt.getIssuedAt() != null
                  && jwt.getExpiresAt() != null;
          boolean lifetimeOk =
              present
                  && Duration.between(jwt.getIssuedAt(), jwt.getExpiresAt()).getSeconds()
                      <= auth.maxTtlSeconds();
          return audienceOk && rolesOk && present && lifetimeOk
              ? OAuth2TokenValidatorResult.success()
              : OAuth2TokenValidatorResult.failure(
                  new OAuth2Error("invalid_token", "token claims are not acceptable", null));
        };
    return new DelegatingOAuth2TokenValidator<>(
        new JwtTimestampValidator(Duration.ofSeconds(30)), new JwtIssuerValidator(issuer), claims);
  }

  /**
   * CORS policy for {@code /api/**}, limited to the configured origins.
   *
   * @return the CORS configuration source
   */
  @Bean
  public CorsConfigurationSource corsConfigurationSource() {
    CorsConfiguration configuration = new CorsConfiguration();
    configuration.setAllowedOrigins(allowedOrigins);
    configuration.setAllowedMethods(List.of("GET", "POST", "OPTIONS"));
    configuration.setAllowedHeaders(List.of("Authorization", "Content-Type", "Last-Event-ID"));
    configuration.setAllowCredentials(true);
    configuration.setMaxAge(3600L);
    UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
    source.registerCorsConfiguration("/api/**", configuration);
    return source;
  }
}
