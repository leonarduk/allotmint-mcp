package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * Tests for {@link AllotMintFilesTool} covering the security boundary: feature-flag gating,
 * path-traversal rejection, and root scoping.
 *
 * <p>These tests exercise the tool's {@code specification(Path)} factory and call handler directly
 * against a temporary directory — no Spring context or MCP transport is needed.
 */
class AllotMintFilesToolTest {

  @TempDir Path tempDir;

  private Path root;
  private McpServerFeatures.SyncToolSpecification spec;

  @BeforeEach
  void setUp() throws IOException {
    // Create a nested root to exercise relative-path resolution
    root = tempDir.resolve("files-root");
    Files.createDirectories(root);

    // Create a known file and subdirectory for read/list/search tests
    Files.writeString(root.resolve("hello.txt"), "Hello, AllotMint!");
    Files.createDirectories(root.resolve("sub"));
    Files.writeString(root.resolve("sub").resolve("nested.txt"), "nested content");

    spec = AllotMintFilesTool.specification(root);
  }

  // -- schema ------------------------------------------------------------

  @Test
  void toolNameIsAllotmintFiles() {
    assertThat(spec.tool().name()).isEqualTo("allotmint_files");
  }

  @Test
  void schemaRequiresAction() {
    assertThat(spec.tool().inputSchema().get("required")).isEqualTo(List.of("action"));
  }

  @Test
  void missingActionReturnsError() {
    McpSchema.CallToolResult result = call(Map.of());

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("action is required");
  }

  // -- read --------------------------------------------------------------

  @Test
  void readReturnsFileContent() {
    McpSchema.CallToolResult result = call(Map.of("action", "read", "path", "hello.txt"));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(text(result)).isEqualTo("Hello, AllotMint!");
  }

  @Test
  void readWithoutPathReturnsError() {
    McpSchema.CallToolResult result = call(Map.of("action", "read"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("path is required");
  }

  @Test
  void readNonExistentFileReturnsError() {
    McpSchema.CallToolResult result = call(Map.of("action", "read", "path", "nonexistent.txt"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  // -- list --------------------------------------------------------------

  @Test
  void listRootReturnsEntries() {
    McpSchema.CallToolResult result = call(Map.of("action", "list"));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    assertThat(structured).containsEntry("action", "list");

    @SuppressWarnings("unchecked")
    List<Map<String, Object>> entries = (List<Map<String, Object>>) structured.get("entries");
    assertThat(entries).hasSize(2);
    assertThat(entries.stream().map(e -> e.get("name"))).contains("hello.txt", "sub");
  }

  @Test
  void listSubdirectory() {
    McpSchema.CallToolResult result = call(Map.of("action", "list", "path", "sub"));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();

    @SuppressWarnings("unchecked")
    List<Map<String, Object>> entries = (List<Map<String, Object>>) structured.get("entries");
    assertThat(entries).hasSize(1);
    assertThat(entries.get(0)).containsEntry("name", "nested.txt");
  }

  // -- search ------------------------------------------------------------

  @Test
  void searchWithoutPatternReturnsError() {
    McpSchema.CallToolResult result = call(Map.of("action", "search"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("pattern is required");
  }

  @Test
  void searchFindsMatchingFiles() {
    McpSchema.CallToolResult result = call(Map.of("action", "search", "pattern", "*.txt"));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    assertThat(structured).containsEntry("pattern", "*.txt");

    @SuppressWarnings("unchecked")
    List<String> matches = (List<String>) structured.get("matches");
    assertThat(matches).contains("hello.txt", "sub/nested.txt");
  }

  @Test
  void searchWithNoMatchesReturnsEmpty() {
    McpSchema.CallToolResult result = call(Map.of("action", "search", "pattern", "*.java"));

    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();

    @SuppressWarnings("unchecked")
    List<String> matches = (List<String>) structured.get("matches");
    assertThat(matches).isEmpty();
  }

  // -- path traversal: dot-dot-slash -------------------------------------

  @Test
  void rejectsDotDotTraversal() {
    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "../../etc/passwd"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  @Test
  void rejectsDotDotTraversalDisguisedInMiddle() {
    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "sub/../../../etc/passwd"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  // -- path traversal: absolute path -------------------------------------

  @Test
  void rejectsAbsoluteUnixPath() {
    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "/etc/passwd"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  @Test
  void rejectsAbsoluteWindowsPath() {
    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "C:\\Windows\\System32\\config\\SAM"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  // -- path traversal: URL-encoded sequences -----------------------------

  @Test
  void rejectsUrlEncodedDotDotTraversal() {
    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "%2e%2e%2f%2e%2e%2fetc%2fpasswd"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  @Test
  void rejectsMixedUrlEncodedTraversal() {
    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "sub/%2e%2e/%2e%2e/etc/passwd"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  // -- path traversal: sibling directory bypass --------------------------

  @Test
  void rejectsSiblingDirectoryPathPrefixBypass() throws IOException {
    // Create /tmp/root-eviltwin next to /tmp/root so string-prefix matching
    // would wrongly allow it
    Path evilTwin = tempDir.resolve("root-eviltwin");
    Files.createDirectories(evilTwin);
    Files.writeString(evilTwin.resolve("secret.txt"), "evil");

    // Path.of("..") + "root-eviltwin/secret.txt" = traverses up out of root
    // then into the sibling.  normalize() should collapse this into
    // tempDir/root-eviltwin/secret.txt which is outside files-root.
    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "../root-eviltwin/secret.txt"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  // -- path traversal: symlink escape ------------------------------------

  @Test
  void rejectsSymlinkEscape() throws IOException {
    // Create a target outside the root
    Path outside = tempDir.resolve("outside.txt");
    Files.writeString(outside, "secret outside root");

    // Create a symlink inside root pointing outside
    Path link = root.resolve("escape.link");
    try {
      Files.createSymbolicLink(link, outside);
    } catch (UnsupportedOperationException | IOException e) {
      // Symlink creation requires privileges on some platforms (Windows without
      // developer mode, restricted CI). Skip the test rather than failing.
      assumeTrue(false, "Symlink creation not supported in this environment: " + e.getMessage());
      return;
    }

    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "escape.link"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  // -- root scoping: valid relative paths --------------------------------

  @Test
  void readNestedFile() {
    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "sub/nested.txt"));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(text(result)).isEqualTo("nested content");
  }

  @Test
  void readWithNormalizedPath() {
    // sub/../hello.txt should resolve to hello.txt within root
    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "sub/../hello.txt"));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(text(result)).isEqualTo("Hello, AllotMint!");
  }

  // -- helpers -----------------------------------------------------------

  private McpSchema.CallToolResult call(Map<String, Object> arguments) {
    return spec
        .callHandler()
        .apply(null, new McpSchema.CallToolRequest("allotmint_files", arguments));
  }

  private static String text(McpSchema.CallToolResult result) {
    return ((McpSchema.TextContent) result.content().getFirst()).text();
  }
}
