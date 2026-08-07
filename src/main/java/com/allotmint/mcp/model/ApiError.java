package com.allotmint.mcp.model;

import com.allotmint.mcp.exception.GlobalExceptionHandler;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

/** Structured JSON error body returned by {@link GlobalExceptionHandler}. */
public record ApiError(int status, String error, String message) {

  public static ApiError of(HttpStatus status, String error, String message) {
    return new ApiError(status.value(), error, message);
  }

  public ResponseEntity<ApiError> toResponse() {
    return ResponseEntity.status(status).body(this);
  }
}
