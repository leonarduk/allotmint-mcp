package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class AllotMintClientInstrumentTest {

  private AllotMintClient client;
  private MockRestServiceServer server;

  @BeforeEach
  void setUp() {
    RestClient.Builder builder = RestClient.builder().baseUrl("http://allotmint.test");
    server = MockRestServiceServer.bindTo(builder).build();
    client = new AllotMintClient(builder.build(), "http://allotmint.test");
  }

  @Test
  void searchesUsingTheInstrumentSearchEndpoint() {
    server
        .expect(requestTo("http://allotmint.test/instrument/search?q=Apple%20Inc"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess(
                "[{\"ticker\":\"AAPL\",\"name\":\"Apple Inc\"}]", MediaType.APPLICATION_JSON));

    List<Map<String, Object>> result = client.searchInstruments("Apple Inc");

    assertThat(result).singleElement().containsEntry("ticker", "AAPL");
    server.verify();
  }

  @Test
  void getsDetailFromTheRouterRootWithJsonFormat() {
    server
        .expect(requestTo("http://allotmint.test/instrument?ticker=AAPL&format=json"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess(
                "{\"ticker\":\"AAPL\",\"prices\":[],\"positions\":[]}",
                MediaType.APPLICATION_JSON));

    Map<String, Object> result = client.instrumentDetail("AAPL");

    assertThat(result).containsEntry("ticker", "AAPL").containsKeys("prices", "positions");
    server.verify();
  }

  @Test
  void getsLatestPriceFromTheQuotesEndpoint() {
    server
        .expect(requestTo("http://allotmint.test/api/quotes?symbols=AAPL"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess(
                "[{\"symbol\":\"AAPL\",\"price\":210.5,\"previous_close\":208.0}]",
                MediaType.APPLICATION_JSON));

    List<Map<String, Object>> result = client.latestQuotes("AAPL");

    assertThat(result).singleElement().containsEntry("price", 210.5);
    server.verify();
  }

  @Test
  void getsNewsUsingTheTickerQueryParameter() {
    server
        .expect(requestTo("http://allotmint.test/news?ticker=AAPL"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess(
                "[{\"headline\":\"Apple headline\",\"url\":\"https://example.test/news\"}]",
                MediaType.APPLICATION_JSON));

    List<Map<String, Object>> result = client.instrumentNews("AAPL");

    assertThat(result).singleElement().containsEntry("headline", "Apple headline");
    server.verify();
  }
}
