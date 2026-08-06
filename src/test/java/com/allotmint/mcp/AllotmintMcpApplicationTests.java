package com.allotmint.mcp;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties = "mcp.stdio.enabled=false")
class AllotmintMcpApplicationTests {

  @Test
  void contextLoads() {}
}
