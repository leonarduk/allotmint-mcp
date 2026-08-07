package com.allotmint.mcp.error;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

/**
 * {@code @WebMvcTest} auto-detects {@code @ControllerAdvice} beans regardless of the {@code
 * controllers} attribute, so {@link GlobalExceptionHandler} is wired in automatically alongside the
 * test-only {@link FailingTestController}.
 *
 * <p>{@code spring.main.web-application-type=none} in the main {@code application.properties}
 * (stdio is the default transport - see {@code StdioMcpServerConfig}) would otherwise leave this
 * slice without a servlet context to back {@link MockMvc}, so it's overridden back to {@code
 * servlet} here, same as {@code application-http.properties} does for the real HTTP transport.
 */
@WebMvcTest(controllers = FailingTestController.class)
@TestPropertySource(properties = "spring.main.web-application-type=servlet")
class GlobalExceptionHandlerTest {

  @Autowired private MockMvc mockMvc;

  @Test
  void missingRequiredParameterReturnsAStructuredFourHundredResponse() throws Exception {
    mockMvc
        .perform(get("/test/needs-param"))
        .andExpect(status().isBadRequest())
        .andExpect(content().contentType(MediaType.APPLICATION_JSON))
        .andExpect(jsonPath("$.status").value(400))
        .andExpect(jsonPath("$.error").value("bad_request"));
  }

  @Test
  void unmappedPathReturnsAStructuredFourOhFourResponse() throws Exception {
    mockMvc
        .perform(get("/test/does-not-exist"))
        .andExpect(status().isNotFound())
        .andExpect(content().contentType(MediaType.APPLICATION_JSON))
        .andExpect(jsonPath("$.status").value(404))
        .andExpect(jsonPath("$.error").value("not_found"));
  }

  @Test
  void unexpectedExceptionReturnsAStructuredFiveHundredResponseWithoutLeakingTheStackTrace()
      throws Exception {
    mockMvc
        .perform(get("/test/boom"))
        .andExpect(status().isInternalServerError())
        .andExpect(content().contentType(MediaType.APPLICATION_JSON))
        .andExpect(jsonPath("$.status").value(500))
        .andExpect(jsonPath("$.error").value("internal_error"))
        .andExpect(jsonPath("$.message").value("An unexpected error occurred"));
  }
}
