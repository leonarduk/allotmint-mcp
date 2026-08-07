package com.allotmint.mcp.client;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class AllotMintClientMarketTest {

  private MockRestServiceServer server;
  private AllotMintClient client;

  @BeforeEach
  void setUp() {
    RestClient.Builder builder = RestClient.builder().baseUrl("http://allotmint.test");
    server = MockRestServiceServer.bindTo(builder).build();
    client = new AllotMintClient(builder.build(), "http://allotmint.test");
  }

  @Test
  void marketOverviewCallsOnlyTheCombinedOverviewEndpoint() {
    server
        .expect(requestTo("http://allotmint.test/market/overview"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess(
                "{\"indexes\":{\"FTSE 100\":{\"level\":8200}},\"sectors\":[],\"headlines\":[]}",
                MediaType.APPLICATION_JSON));

    Map<String, Object> response = client.marketOverview();

    assertThat(response).containsOnlyKeys("indexes", "sectors", "headlines");
    server.verify();
  }

  @Test
  void marketMoversCallsTheStandaloneMoversEndpoint() {
    server
        .expect(requestTo("http://allotmint.test/movers"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess(
                "{\"gainers\":[{\"ticker\":\"AAA\"}],\"losers\":[]}", MediaType.APPLICATION_JSON));

    Map<String, Object> response = client.marketMovers();

    assertThat(response).containsOnlyKeys("gainers", "losers");
    server.verify();
  }
}
