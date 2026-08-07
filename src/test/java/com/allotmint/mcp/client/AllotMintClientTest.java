package com.allotmint.mcp.client;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withUnauthorizedRequest;

import com.allotmint.mcp.error.AllotMintApiException;
import com.allotmint.mcp.pojo.AllotMintHealthStatus;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

public class AllotMintClientTest {

  private static final String BASE_URL = "https://api.example.test";

  @Test
  void reportsBackendVersionWhenReachable() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    AllotMintClient client = new AllotMintClient(builder.build(), BASE_URL);

    server
        .expect(requestTo(BASE_URL + "/openapi.json"))
        .andRespond(withSuccess("{\"info\":{\"version\":\"1.2.3\"}}", MediaType.APPLICATION_JSON));

    assertThat(client.health()).isEqualTo(new AllotMintHealthStatus(true, "1.2.3", BASE_URL));
    server.verify();
  }

  @Test
  void reportsUnreachableWhenBackendReturnsUnauthorized() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    AllotMintClient client = new AllotMintClient(builder.build(), BASE_URL);

    server.expect(requestTo(BASE_URL + "/openapi.json")).andRespond(withUnauthorizedRequest());

    assertThat(client.health()).isEqualTo(new AllotMintHealthStatus(false, null, BASE_URL));
    server.verify();
  }

  @Test
  void mapsUnauthorizedResponseToClearAuthErrorOnDataCalls() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    AllotMintClient client = new AllotMintClient(builder.build(), BASE_URL);

    server.expect(requestTo(BASE_URL + "/portfolio/demo")).andRespond(withUnauthorizedRequest());

    assertThatThrownBy(() -> client.portfolio("demo"))
        .isInstanceOf(AllotMintApiException.class)
        .hasMessage(AllotMintClient.AUTH_ERROR_MESSAGE);
    server.verify();
  }
}
