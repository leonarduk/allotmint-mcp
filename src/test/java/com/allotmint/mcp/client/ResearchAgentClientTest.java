package com.allotmint.mcp.client;

import com.allotmint.mcp.exception.AllotMintApiException;
import com.allotmint.mcp.model.ResearchAnswer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class ResearchAgentClientTest {

  private static final String BASE_URL = "http://research.test";

  private MockRestServiceServer server;
  private ResearchAgentClient client;

  @BeforeEach
  void setUp() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    server = MockRestServiceServer.bindTo(builder).build();
    client = new ResearchAgentClient(builder.build(), BASE_URL);
  }

  @Test
  void postsTheQuestionAndParsesTheGroundedAnswer() {
    server
        .expect(requestTo(BASE_URL + "/research/ask"))
        .andExpect(method(HttpMethod.POST))
        .andExpect(content().contentType(MediaType.APPLICATION_JSON))
        .andExpect(jsonPath("$.question").value("how has my tech exposure changed?"))
        .andExpect(jsonPath("$.owner").value("demo"))
        .andExpect(jsonPath("$.lookback_days").value(365))
        .andRespond(
            withSuccess(
                """
                {
                  "question": "how has my tech exposure changed?",
                  "answer": "Technology rose from 18% to 27% [1].",
                  "citations": [
                    {"id": 1, "kind": "document", "ref": "report:portfolio.sectors",
                     "detail": "cosine distance 0.6171", "excerpt": "Technology 27.0%"},
                    {"id": 2, "kind": "tool_call", "ref": "allotmint_portfolio",
                     "detail": "allotmint_portfolio(action='exposure')", "excerpt": "{}"}
                  ],
                  "tool_calls": [
                    {"tool": "allotmint_portfolio",
                     "arguments": {"action": "exposure", "owner": "demo"},
                     "result_excerpt": "{}"}
                  ],
                  "retrieved_documents": [],
                  "grounded": true,
                  "warnings": [],
                  "model": "ollama:llama3.2"
                }
                """,
                MediaType.APPLICATION_JSON));

    ResearchAnswer answer = client.ask("how has my tech exposure changed?", "demo", 365);

    assertThat(answer.grounded()).isTrue();
    assertThat(answer.answer()).contains("18% to 27% [1]");
    assertThat(answer.model()).isEqualTo("ollama:llama3.2");
    assertThat(answer.citationsOrEmpty()).hasSize(2);
    assertThat(answer.citationsOrEmpty().getFirst().ref()).isEqualTo("report:portfolio.sectors");
    assertThat(answer.toolCallsOrEmpty()).hasSize(1);
    assertThat(answer.toolCallsOrEmpty().getFirst().arguments())
        .containsEntry("action", "exposure");
    server.verify();
  }

  @Test
  void omitsOwnerFromThePayloadWhenAbsent() {
    server
        .expect(requestTo(BASE_URL + "/research/ask"))
        .andExpect(jsonPath("$.owner").doesNotExist())
        .andRespond(
            withSuccess("{\"answer\":\"...\",\"grounded\":true}", MediaType.APPLICATION_JSON));

    client.ask("what is the market doing?", null, 30);

    server.verify();
  }

  @Test
  void toleratesUnknownFieldsInTheAgentResponse() {
    // The sidecar may grow response fields ahead of the Java side; that must
    // not turn a working answer into a deserialization failure.
    server
        .expect(requestTo(BASE_URL + "/research/ask"))
        .andRespond(
            withSuccess(
                "{\"answer\":\"ok\",\"grounded\":true,\"trace_id\":\"abc\",\"cost_usd\":0}",
                MediaType.APPLICATION_JSON));

    ResearchAnswer answer = client.ask("why?", null, 365);

    assertThat(answer.answer()).isEqualTo("ok");
    assertThat(answer.citationsOrEmpty()).isEmpty();
    assertThat(answer.warningsOrEmpty()).isEmpty();
  }

  @Test
  void mapsAnErrorResponseToAReadableException() {
    server
        .expect(requestTo(BASE_URL + "/research/ask"))
        .andRespond(
            withServerError()
                .body("{\"detail\":\"research run failed: connection refused\"}")
                .contentType(MediaType.APPLICATION_JSON));

    assertThatThrownBy(() -> client.ask("why?", "demo", 365))
        .isInstanceOf(AllotMintApiException.class)
        .hasMessageContaining("Research agent returned 500")
        .hasMessageContaining("connection refused");
  }
}
