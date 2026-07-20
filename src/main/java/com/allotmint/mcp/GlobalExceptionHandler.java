package com.allotmint.mcp;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.NoHandlerFoundException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/**
 * Maps uncaught exceptions from the HTTP transport's annotated controllers to a consistent JSON
 * error body instead of Spring's default stack-trace/whitelabel responses. Only applies to
 * {@code @Controller}/{@code @RestController} beans; the MCP router function registered by {@link
 * McpServerConfig} handles its own protocol-level errors per the MCP spec and isn't routed through
 * this advice.
 */
@RestControllerAdvice
class GlobalExceptionHandler {

  private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

  @ExceptionHandler(MissingServletRequestParameterException.class)
  ResponseEntity<ApiError> handleBadRequest(MissingServletRequestParameterException ex) {
    return ApiError.of(HttpStatus.BAD_REQUEST, "bad_request", ex.getMessage()).toResponse();
  }

  /**
   * {@code NoResourceFoundException} is thrown by Boot's default static-resource handler; {@code
   * NoHandlerFoundException} is what this app's own {@code @EnableWebMvc}-based HTTP config (see
   * {@link McpServerConfig}) throws instead for an unmapped path, since {@code @EnableWebMvc} opts
   * out of that default resource handler. Both mean the same thing to a client: nothing was found
   * at this path.
   */
  @ExceptionHandler({NoResourceFoundException.class, NoHandlerFoundException.class})
  ResponseEntity<ApiError> handleNotFound(Exception ex) {
    return ApiError.of(HttpStatus.NOT_FOUND, "not_found", "The requested resource was not found")
        .toResponse();
  }

  @ExceptionHandler(Exception.class)
  ResponseEntity<ApiError> handleUnexpected(Exception ex) {
    log.error("Unhandled exception in HTTP transport", ex);
    return ApiError.of(
            HttpStatus.INTERNAL_SERVER_ERROR, "internal_error", "An unexpected error occurred")
        .toResponse();
  }
}
