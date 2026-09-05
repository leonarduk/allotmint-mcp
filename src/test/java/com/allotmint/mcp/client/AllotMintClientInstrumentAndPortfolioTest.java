package com.allotmint.mcp.client;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * Covers the {@link AllotMintClient} wrapper methods that no other test exercises against a real
 * {@link RestClient} - they're only invoked through mocked-{@code AllotMintClient} tool tests
 * elsewhere, which stub the return value rather than running this class's HTTP-building code.
 */
class AllotMintClientInstrumentAndPortfolioTest {

  private static final String BASE_URL = "http://allotmint.test";

  private MockRestServiceServer server;
  private AllotMintClient client;

  @BeforeEach
  void setUp() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    server = MockRestServiceServer.bindTo(builder).build();
    RestClient restClient = builder.build();
    client = new AllotMintClient(restClient, restClient, BASE_URL);
  }

  @Test
  void portfolioSectorsCallsTheCurrentSnapshotEndpoint() {
    server
        .expect(requestTo(BASE_URL + "/portfolio/alice/sectors"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess(
                "[{\"sector\":\"Technology\",\"weight\":0.4}]", MediaType.APPLICATION_JSON));

    List<Map<String, Object>> response = client.portfolioSectors("alice");

    assertThat(response).extracting(s -> s.get("sector")).containsExactly("Technology");
    server.verify();
  }

  @Test
  void portfolioSectorsWithLookbackPassesLookbackDaysAsAQueryParameter() {
    // as_of is the only date parameter the sectors endpoint accepts; lookback_days was
    // silently discarded by FastAPI, so every "historical" call returned the current snapshot.
    server
        .expect(requestTo(BASE_URL + "/portfolio/alice/sectors?as_of=2025-09-05"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess(
                "[{\"sector\":\"Technology\",\"weight_pct\":35.0}]",
                MediaType.APPLICATION_JSON));

    List<Map<String, Object>> response =
        client.portfolioSectors("alice", LocalDate.of(2025, 9, 5));

    assertThat(response).extracting(s -> s.get("weight_pct")).containsExactly(35.0);
    server.verify();
  }

  @Test
  void performanceCallsThePerformanceEndpointForTheOwner() {
    server
        .expect(requestTo(BASE_URL + "/performance/alice"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(withSuccess("{\"totalReturn\":0.12}", MediaType.APPLICATION_JSON));

    Map<String, Object> response = client.performance("alice");

    assertThat(response).containsEntry("totalReturn", 0.12);
    server.verify();
  }

  @Test
  void instrumentSearchPassesTheQueryStringAsAQueryParameter() {
    server
        .expect(requestTo(BASE_URL + "/instrument/search?q=vod"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess(
                "[{\"ticker\":\"VOD.L\",\"name\":\"Vodafone\"}]", MediaType.APPLICATION_JSON));

    List<Map<String, Object>> response = client.instrumentSearch("vod");

    assertThat(response).extracting(i -> i.get("ticker")).containsExactly("VOD.L");
    server.verify();
  }

  @Test
  void instrumentDetailRequestsJsonFormatForTheGivenTicker() {
    server
        .expect(requestTo(BASE_URL + "/instrument?ticker=VOD.L&format=json"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess("{\"ticker\":\"VOD.L\",\"history\":[]}", MediaType.APPLICATION_JSON));

    Map<String, Object> response = client.instrumentDetail("VOD.L");

    assertThat(response).containsEntry("ticker", "VOD.L");
    server.verify();
  }

  @Test
  void quotesRequestsASingleSymbolFromTheApiQuotesEndpoint() {
    server
        .expect(requestTo(BASE_URL + "/api/quotes?symbols=VOD.L"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess("[{\"symbol\":\"VOD.L\",\"price\":75.2}]", MediaType.APPLICATION_JSON));

    List<Map<String, Object>> response = client.quotes("VOD.L");

    assertThat(response).extracting(q -> q.get("price")).containsExactly(75.2);
    server.verify();
  }

  @Test
  void newsRequestsHeadlinesForTheGivenTicker() {
    server
        .expect(requestTo(BASE_URL + "/news?ticker=VOD.L"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(
            withSuccess(
                "[{\"headline\":\"Vodafone reports earnings\"}]", MediaType.APPLICATION_JSON));

    List<Map<String, Object>> response = client.news("VOD.L");

    assertThat(response)
        .extracting(n -> n.get("headline"))
        .containsExactly("Vodafone reports earnings");
    server.verify();
  }
}
