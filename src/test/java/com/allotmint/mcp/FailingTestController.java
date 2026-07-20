package com.allotmint.mcp;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Test-only controller used by {@link GlobalExceptionHandlerTest} to trigger errors. */
@RestController
public class FailingTestController {

  @GetMapping("/test/needs-param")
  public String needsParam(@RequestParam String name) {
    return "hello " + name;
  }

  @GetMapping("/test/boom")
  public String boom() {
    throw new IllegalStateException("kaboom, with sensitive internal detail");
  }
}
