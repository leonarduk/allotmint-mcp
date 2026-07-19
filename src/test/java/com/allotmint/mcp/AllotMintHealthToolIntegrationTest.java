package com.allotmint.mcp;

import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * TODO(#4): integration test for {@code allotmint_health}, per the issue's success
 * criteria:
 *
 * "Integration test passes against a local AllotMint backend started with
 * {@code DISABLE_AUTH=true}."
 *
 * Suggested approach:
 * <ol>
 *   <li>Start the AllotMint backend out-of-process before the test class (a shell
 *       script the test shells out to, or a manually-started process the CI job
 *       brings up first - decide which fits this repo's CI setup) with
 *       {@code DISABLE_AUTH=true} so no auth token is needed.</li>
 *   <li>Point {@code allotmint.api.base-url} at that instance, e.g. via
 *       {@code @SpringBootTest(properties = "allotmint.api.base-url=http://localhost:8000")}
 *       or a {@code src/test/resources/application-integration.properties} profile.</li>
 *   <li>Call the tool the same way an MCP client would - either invoke
 *       {@code AllotMintHealthTool.specification(client)}'s callHandler directly, or
 *       (closer to the real thing) drive it through {@code McpSyncServer} /
 *       {@code McpClient} over stdio, matching how {@link AllotmintMcpApplicationTests}
 *       exercises context startup.</li>
 *   <li>Assert the result is {@code {reachable: true, version: ..., baseUrl: ...}}.</li>
 * </ol>
 *
 * Left {@code @Disabled} because it depends on a real AllotMint backend being
 * reachable, which isn't available in a plain {@code mvn test} run - un-disable once
 * wired into whatever local/CI harness starts that backend.
 */
@SpringBootTest
class AllotMintHealthToolIntegrationTest {

    @Test
    @Disabled("TODO(#4): implement against a local AllotMint backend started with DISABLE_AUTH=true")
    void allotmintHealthReportsReachableBackend() {
    }
}
