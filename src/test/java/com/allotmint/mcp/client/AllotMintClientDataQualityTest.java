package com.allotmint.mcp.client;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class AllotMintClientDataQualityTest {

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
  void issuesPassesProvidedFiltersAsQueryParameters() {
    server
        .expect(requestTo(BASE_URL + "/data-quality/issues?type=WRONG_EXCHANGE&severity=high"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(withSuccess("{\"count\":1,\"issues\":[]}", MediaType.APPLICATION_JSON));

    Map<String, String> filters = new LinkedHashMap<>();
    filters.put("type", "WRONG_EXCHANGE");
    filters.put("severity", "high");
    Map<String, Object> response = client.dataQualityIssues(filters);

    assertThat(response).containsEntry("count", 1);
    server.verify();
  }

  @Test
  void issuesSkipsNullAndBlankFilterValuesSoNoEmptyQueryParametersAreSent() {
    server
        .expect(requestTo(BASE_URL + "/data-quality/issues?type=WRONG_EXCHANGE"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(withSuccess("{\"count\":0,\"issues\":[]}", MediaType.APPLICATION_JSON));

    Map<String, String> filters = new LinkedHashMap<>();
    filters.put("type", "WRONG_EXCHANGE");
    filters.put("severity", null);
    filters.put("owner", "");
    filters.put("ticker", "   ");
    Map<String, Object> response = client.dataQualityIssues(filters);

    assertThat(response).containsEntry("count", 0);
    server.verify();
  }

  @Test
  void previewEncodesReservedCharactersInTheIssueIdPathSegment() {
    server
        .expect(requestTo(BASE_URL + "/data-quality/issues/issue%2F123/preview"))
        .andExpect(method(HttpMethod.GET))
        .andRespond(withSuccess("{\"id\":\"issue/123\"}", MediaType.APPLICATION_JSON));

    Map<String, Object> response = client.dataQualityPreview("issue/123");

    assertThat(response).containsEntry("id", "issue/123");
    server.verify();
  }

  @Test
  void dedupeEncodesTickerAndExchangePathSegments() {
    server
        .expect(requestTo(BASE_URL + "/data-quality/series/MICC%2FL/L/dedupe"))
        .andExpect(method(HttpMethod.POST))
        .andRespond(withSuccess("{\"status\":\"fixed\"}", MediaType.APPLICATION_JSON));

    Map<String, Object> response = client.dataQualityDedupe("MICC/L", "L", true);

    assertThat(response).containsEntry("status", "fixed");
    server.verify();
  }

  @Test
  void undoEncodesTheAuditIdPathSegment() {
    server
        .expect(requestTo(BASE_URL + "/data-quality/audit/audit%2F1/undo"))
        .andExpect(method(HttpMethod.POST))
        .andRespond(withSuccess("{\"status\":\"undone\"}", MediaType.APPLICATION_JSON));

    Map<String, Object> response = client.dataQualityUndo("audit/1", true);

    assertThat(response).containsEntry("status", "undone");
    server.verify();
  }

  @Test
  void fixRefusesToCallTheBackendWithoutConfirm() {
    assertThatThrownBy(() -> client.dataQualityFix("i1", false))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("confirm=true");
  }

  @Test
  void dedupeRefusesToCallTheBackendWithoutConfirm() {
    assertThatThrownBy(() -> client.dataQualityDedupe("MICC", "L", false))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("confirm=true");
  }

  @Test
  void undoRefusesToCallTheBackendWithoutConfirm() {
    assertThatThrownBy(() -> client.dataQualityUndo("aud-1", false))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("confirm=true");
  }

  @Test
  void fixPostsToTheIssueEndpointWhenConfirmed() {
    server
        .expect(requestTo(BASE_URL + "/data-quality/issues/i1/fix"))
        .andExpect(method(HttpMethod.POST))
        .andRespond(
            withSuccess(
                "{\"status\":\"fixed\",\"audit_id\":\"aud-1\"}", MediaType.APPLICATION_JSON));

    Map<String, Object> response = client.dataQualityFix("i1", true);

    assertThat(response).containsEntry("status", "fixed").containsEntry("audit_id", "aud-1");
    server.verify();
  }
}
