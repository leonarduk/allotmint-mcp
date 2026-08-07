package com.allotmint.mcp.config;

import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.headerDoesNotExist;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import com.allotmint.mcp.config.AllotMintClientConfig;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class AllotMintClientConfigTest {

  private static final String BASE_URL = "https://api.example.test";

  @Test
  void attachesConfiguredBearerTokenToEveryRequest() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    RestClient client =
        AllotMintClientConfig.withAuthorization(builder, "backend.jwt.token").build();

    server
        .expect(requestTo(BASE_URL + "/probe"))
        .andExpect(header(HttpHeaders.AUTHORIZATION, "Bearer backend.jwt.token"))
        .andRespond(withSuccess());

    client.get().uri("/probe").retrieve().toBodilessEntity();
    server.verify();
  }

  @Test
  void omitsAuthorizationHeaderWhenTokenIsBlank() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    RestClient client = AllotMintClientConfig.withAuthorization(builder, "   ").build();

    server
        .expect(requestTo(BASE_URL + "/probe"))
        .andExpect(headerDoesNotExist(HttpHeaders.AUTHORIZATION))
        .andRespond(withSuccess());

    client.get().uri("/probe").retrieve().toBodilessEntity();
    server.verify();
  }
}
