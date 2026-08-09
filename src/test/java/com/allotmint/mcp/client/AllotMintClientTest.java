package com.allotmint.mcp.client;

import com.allotmint.mcp.exception.AllotMintApiException;
import com.allotmint.mcp.model.AllotMintHealthStatus;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.http.HttpMethod.POST;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withUnauthorizedRequest;

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

  @Test
  void postsCsvForReadOnlyReconciliation() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    AllotMintClient client = new AllotMintClient(builder.build(), BASE_URL);
    server
        .expect(requestTo(BASE_URL + "/holdings/reconcile"))
        .andExpect(method(POST))
        .andExpect(
            content()
                .json(
                    """
                    {"owner":"alice","account_type":"SIPP","csv_content":"Ticker,Quantity\\nVWRL,2"}
                    """))
        .andRespond(withSuccess("{\"reconciliation_id\":\"rec-1\"}", MediaType.APPLICATION_JSON));

    assertThat(client.reconcileHoldings("alice", "SIPP", "Ticker,Quantity\nVWRL,2"))
        .containsEntry("reconciliation_id", "rec-1");
    server.verify();
  }

  @Test
  void appliesOnlyBackendIssuedReconciliationId() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    AllotMintClient client = new AllotMintClient(builder.build(), BASE_URL);
    server
        .expect(requestTo(BASE_URL + "/holdings/reconcile/apply"))
        .andExpect(method(POST))
        .andExpect(content().json("{\"reconciliation_id\":\"rec-1\"}"))
        .andRespond(withSuccess("{\"status\":\"applied\"}", MediaType.APPLICATION_JSON));

    assertThat(client.applyReconciliation("rec-1")).containsEntry("status", "applied");
    server.verify();
  }
}
