package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;
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
    root = tempDir.resolve("files-root");
    Files.createDirectories(root);

    Files.writeString(root.resolve("hello.txt"), "Hello, AllotMint!");
    Files.createDirectories(root.resolve("sub"));
    Files.writeString(root.resolve("sub").resolve("nested.txt"), "nested content");
    // File with a plus sign to verify URL decoding preserves '+'
    Files.writeString(root.resolve("a+b.txt"), "plus sign preserved");

    spec = AllotMintFilesTool.specification(root);
  }

  // -- null/empty root validation -----------------------------------------

  @Test
  void specificationRejectsNullRoot() {
    assertThatIllegalArgumentException()
        .isThrownBy(() -> AllotMintFilesTool.specification(null))
        .withMessageContaining("ALLOTMINT_MCP_FILES_ROOT is required");
  }

  @Test
  void specificationRejectsNonExistentRoot() {
    assertThatIllegalArgumentException()
        .isThrownBy(() -> AllotMintFilesTool.specification(tempDir.resolve("nonexistent")))
        .withMessageContaining("does not exist");
  }

  @Test
  void specificationRejectsEmptyRoot() {
    assertThatIllegalArgumentException()
        .isThrownBy(() -> AllotMintFilesTool.specification(Path.of("")))
        .withMessageContaining("ALLOTMINT_MCP_FILES_ROOT is required");
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
  void readNonExistentFileReturnsFileNotFound() {
    McpSchema.CallToolResult result = call(Map.of("action", "read", "path", "nonexistent.txt"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("File not found");
  }

  @Test
  void readFileWithPlusSignInName() {
    McpSchema.CallToolResult result = call(Map.of("action", "read", "path", "a+b.txt"));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(text(result)).isEqualTo("plus sign preserved");
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
    assertThat(entries).hasSize(3);
    assertThat(entries.stream().map(e -> e.get("name"))).contains("a+b.txt", "hello.txt", "sub");
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

  @Test
  void listNonExistentDirectoryReturnsDirectoryNotFound() {
    McpSchema.CallToolResult result = call(Map.of("action", "list", "path", "nonexistent"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Directory not found");
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
    assertThat(matches).contains("a+b.txt", "hello.txt", "sub/nested.txt");
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

  @Test
  void searchRejectsTraversalPattern() {
    McpSchema.CallToolResult result = call(Map.of("action", "search", "pattern", "../../etc/*"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("path traversal");
  }

  @Test
  void searchRejectsMalformedPattern() {
    McpSchema.CallToolResult result = call(Map.of("action", "search", "pattern", "["));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Invalid search pattern");
  }

  @Test
  void searchTruncatesAtMaxMatches() throws IOException {
    Path many = root.resolve("many");
    Files.createDirectories(many);
    for (int i = 0; i < 510; i++) {
      Files.writeString(many.resolve("f" + i + ".dat"), "x");
    }

    McpSchema.CallToolResult result = call(Map.of("action", "search", "pattern", "**/*.dat"));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    assertThat(structured).containsEntry("truncated", true);

    @SuppressWarnings("unchecked")
    List<String> matches = (List<String>) structured.get("matches");
    assertThat(matches).hasSize(500);
    assertThat(text(result)).contains("truncated");
  }

  // -- path traversal: dot-dot-slash -------------------------------------

  @Test
  void rejectsDotDotTraversal() {
    McpSchema.CallToolResult result = call(Map.of("action", "read", "path", "../../etc/passwd"));

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
    McpSchema.CallToolResult result = call(Map.of("action", "read", "path", "/etc/passwd"));

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

  // -- path traversal: backslash-disguised sequences ----------------------

  @Test
  void rejectsBackslashDisguisedTraversal() {
    // Backslash is only a path separator to java.nio.file.Path on a native
    // Windows host; this must be rejected the same way on every OS.
    McpSchema.CallToolResult result = call(Map.of("action", "read", "path", "..\\..\\etc\\passwd"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  // -- path traversal: URL-encoded sequences -----------------------------

  @Test
  void rejectsUrlEncodedDotDotTraversal() {
    McpSchema.CallToolResult result =
        call(
            Map.of(
                "action", "read",
                "path", "%2e%2e%2f%2e%2e%2fetc%2fpasswd"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  @Test
  void rejectsMixedUrlEncodedTraversal() {
    McpSchema.CallToolResult result =
        call(
            Map.of(
                "action", "read",
                "path", "sub/%2e%2e/%2e%2e/etc/passwd"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  // -- path traversal: sibling directory bypass --------------------------

  @Test
  void rejectsSiblingDirectoryPathPrefixBypass() throws IOException {
    Path evilTwin = tempDir.resolve("root-eviltwin");
    Files.createDirectories(evilTwin);
    Files.writeString(evilTwin.resolve("secret.txt"), "evil");

    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "../root-eviltwin/secret.txt"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  // -- path traversal: symlink escape ------------------------------------

  @Test
  void rejectsSymlinkEscape() throws IOException {
    Path outside = tempDir.resolve("outside.txt");
    Files.writeString(outside, "secret outside root");

    Path link = root.resolve("escape.link");
    try {
      Files.createSymbolicLink(link, outside);
    } catch (UnsupportedOperationException | IOException e) {
      assumeTrue(false, "Symlink creation not supported in this environment: " + e.getMessage());
      return;
    }

    McpSchema.CallToolResult result = call(Map.of("action", "read", "path", "escape.link"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  @Test
  void rejectsSymlinkEscapeInIntermediateComponent() throws IOException {
    Path outsideDir = tempDir.resolve("outside-dir");
    Files.createDirectories(outsideDir);
    Files.writeString(outsideDir.resolve("secret.txt"), "secret outside root");

    Path link = root.resolve("escape-dir.link");
    try {
      Files.createSymbolicLink(link, outsideDir);
    } catch (UnsupportedOperationException | IOException e) {
      assumeTrue(false, "Symlink creation not supported in this environment: " + e.getMessage());
      return;
    }

    McpSchema.CallToolResult result =
        call(Map.of("action", "read", "path", "escape-dir.link/secret.txt"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Path traversal rejected");
  }

  // -- root scoping: valid relative paths --------------------------------

  @Test
  void readNestedFile() {
    McpSchema.CallToolResult result = call(Map.of("action", "read", "path", "sub/nested.txt"));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(text(result)).isEqualTo("nested content");
  }

  @Test
  void readWithNormalizedPath() {
    // sub/../hello.txt should resolve to hello.txt within root
    McpSchema.CallToolResult result = call(Map.of("action", "read", "path", "sub/../hello.txt"));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(text(result)).isEqualTo("Hello, AllotMint!");
  }

  // -- helpers -----------------------------------------------------------

  private McpSchema.CallToolResult call(Map<String, Object> arguments) {
    return spec.callHandler()
        .apply(null, new McpSchema.CallToolRequest("allotmint_files", arguments));
  }

  private static String text(McpSchema.CallToolResult result) {
    return ((McpSchema.TextContent) result.content().getFirst()).text();
  }
}
