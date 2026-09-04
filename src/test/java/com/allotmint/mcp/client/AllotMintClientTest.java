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
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withUnauthorizedRequest;

public class AllotMintClientTest {

  private static final String BASE_URL = "https://api.example.test";

  @Test
  void listsAvailableAccountOwners() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    RestClient restClient = builder.build();
    AllotMintClient client = new AllotMintClient(restClient, restClient, BASE_URL);
    server
        .expect(requestTo(BASE_URL + "/owners"))
        .andRespond(
            withSuccess("[{\"slug\":\"alice\"},{\"slug\":\"bob\"}]", MediaType.APPLICATION_JSON));

    assertThat(client.owners())
        .extracting(owner -> owner.get("slug"))
        .containsExactly("alice", "bob");
    server.verify();
  }

  @Test
  void reportsBackendVersionWhenReachable() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    RestClient restClient = builder.build();
    AllotMintClient client = new AllotMintClient(restClient, restClient, BASE_URL);

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
    RestClient restClient = builder.build();
    AllotMintClient client = new AllotMintClient(restClient, restClient, BASE_URL);

    server.expect(requestTo(BASE_URL + "/openapi.json")).andRespond(withUnauthorizedRequest());

    assertThat(client.health()).isEqualTo(new AllotMintHealthStatus(false, null, BASE_URL));
    server.verify();
  }

  @Test
  void mapsUnauthorizedResponseToClearAuthErrorOnDataCalls() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    RestClient restClient = builder.build();
    AllotMintClient client = new AllotMintClient(restClient, restClient, BASE_URL);

    server.expect(requestTo(BASE_URL + "/portfolio/demo")).andRespond(withUnauthorizedRequest());

    assertThatThrownBy(() -> client.portfolio("demo"))
        .isInstanceOf(AllotMintApiException.class)
        .hasMessage(AllotMintClient.AUTH_ERROR_MESSAGE);
    server.verify();
  }

  @Test
  void postsCsvForReadOnlyReconciliation() {
    RestClient.Builder getBuilder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer getServer = MockRestServiceServer.bindTo(getBuilder).build();
    RestClient.Builder postBuilder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer postServer = MockRestServiceServer.bindTo(postBuilder).build();
    AllotMintClient client = new AllotMintClient(getBuilder.build(), postBuilder.build(), BASE_URL);
    postServer
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
    postServer.verify();
    getServer.verify();
  }

  @Test
  void appliesOnlyBackendIssuedReconciliationId() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    RestClient restClient = builder.build();
    AllotMintClient client = new AllotMintClient(restClient, restClient, BASE_URL);
    server
        .expect(requestTo(BASE_URL + "/holdings/reconcile/apply"))
        .andExpect(method(POST))
        .andExpect(content().json("{\"reconciliation_id\":\"rec-1\"}"))
        .andRespond(withSuccess("{\"status\":\"applied\"}", MediaType.APPLICATION_JSON));

    assertThat(client.applyReconciliation("rec-1")).containsEntry("status", "applied");
    server.verify();
  }

  @Test
  void mapsNonAuthErrorResponseToReadableExceptionWithStatusAndBody() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    RestClient restClient = builder.build();
    AllotMintClient client = new AllotMintClient(restClient, restClient, BASE_URL);

    server
        .expect(requestTo(BASE_URL + "/portfolio/demo"))
        .andRespond(withServerError().body("backend blew up"));

    assertThatThrownBy(() -> client.portfolio("demo"))
        .isInstanceOf(AllotMintApiException.class)
        .hasMessageContaining("AllotMint backend returned 500")
        .hasMessageContaining("backend blew up");
    server.verify();
  }
}
