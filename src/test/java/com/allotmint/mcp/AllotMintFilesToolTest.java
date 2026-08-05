package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
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
 * Unit and focused-integration tests for {@link AllotMintFilesTool}. Covers the core security
 * boundary — resolved-path containment — plus the three operations (read/list/search).
 */
class AllotMintFilesToolTest {

  @TempDir Path tempDir;

  private Path root;

  @BeforeEach
  void setUp() throws IOException {
    root = tempDir.resolve("files-root");
    Files.createDirectory(root);

    // Create a known file for read tests
    Files.writeString(root.resolve("hello.txt"), "Hello, AllotMint!\nLine two.\n");

    // Create a subdirectory with files for list/search tests
    Path sub = root.resolve("subdir");
    Files.createDirectory(sub);
    Files.writeString(sub.resolve("a.txt"), "apple\nbanana\ncherry\n");
    Files.writeString(sub.resolve("b.txt"), "blueberry\nblackberry\n");
    Files.writeString(sub.resolve("deep.md"), "# Markdown\nContent here.\nbanana reference\n");
  }

  // ── resolveAndValidate ─────────────────────────────────────────────────

  @Test
  void resolveValidRelativePath() {
    Path resolved = AllotMintFilesTool.resolveAndValidate(root, "hello.txt");
    assertThat(resolved).isEqualTo(root.resolve("hello.txt").toAbsolutePath().normalize());
  }

  @Test
  void resolveEmptyPathReturnsRoot() {
    Path resolved = AllotMintFilesTool.resolveAndValidate(root, "");
    assertThat(resolved).isEqualTo(root.toAbsolutePath().normalize());
  }

  @Test
  void resolveSubdirectoryPath() {
    Path resolved = AllotMintFilesTool.resolveAndValidate(root, "subdir/a.txt");
    assertThat(resolved).endsWith(Path.of("subdir", "a.txt"));
  }

  @Test
  void rejectDotDotTraversal() {
    assertThatThrownBy(() -> AllotMintFilesTool.resolveAndValidate(root, "../etc/passwd"))
        .isInstanceOf(McpFileAccessException.class)
        .hasMessageContaining("traversal")
        .hasMessageContaining("etc/passwd");
  }

  @Test
  void rejectMultipleDotDotTraversal() {
    assertThatThrownBy(() -> AllotMintFilesTool.resolveAndValidate(root, "../../../../etc/shadow"))
        .isInstanceOf(McpFileAccessException.class)
        .hasMessageContaining("traversal");
  }

  @Test
  void rejectAbsolutePathOutsideRoot() {
    // Use a path that definitely exists but is outside root, e.g. the temp dir parent
    Path outside = tempDir.getParent();
    assertThatThrownBy(() -> AllotMintFilesTool.resolveAndValidate(root, outside.toString()))
        .isInstanceOf(McpFileAccessException.class)
        .hasMessageContaining("traversal");
  }

  @Test
  void rejectSymlinkEscape() throws IOException {
    // Create a symlink inside root that points outside root
    Path outsideFile = tempDir.resolve("secret.txt");
    Files.writeString(outsideFile, "secret");

    Path symlink = root.resolve("escape-link");
    try {
      Files.createSymbolicLink(symlink, outsideFile);
    } catch (UnsupportedOperationException | IOException e) {
      // Symlinks not supported or require privileges (e.g. Windows without developer mode)
      assumeTrue(false, "Skipped: symlink creation not available: " + e.getMessage());
    }

    assertThatThrownBy(() -> AllotMintFilesTool.resolveAndValidate(root, "escape-link"))
        .isInstanceOf(McpFileAccessException.class)
        .hasMessageContaining("traversal");
  }

  // ── operation: read ────────────────────────────────────────────────────

  @Test
  void readFileReturnsContent() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);
    McpSchema.CallToolResult result =
        spec.callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_files",
                    Map.of(
                        AllotMintFilesTool.OPERATION,
                        "read",
                        AllotMintFilesTool.PATH,
                        "hello.txt")));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .anyMatch(
            c -> c instanceof McpSchema.TextContent tc && tc.text().contains("Hello, AllotMint!"));
    assertThat(result.structuredContent())
        .isInstanceOfSatisfying(
            Map.class,
            m -> {
              assertThat(m).containsEntry("path", "hello.txt");
              assertThat(m).containsKey("size");
            });
  }

  @Test
  void readRejectsTraversalPath() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);
    assertThatThrownBy(
            () ->
                spec.callHandler()
                    .apply(
                        null,
                        new McpSchema.CallToolRequest(
                            "allotmint_files",
                            Map.of(
                                AllotMintFilesTool.OPERATION,
                                "read",
                                AllotMintFilesTool.PATH,
                                "../../etc/passwd"))))
        .isInstanceOf(McpFileAccessException.class)
        .hasMessageContaining("traversal");
  }

  @Test
  void readNonExistentFileReturnsError() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);
    McpSchema.CallToolResult result =
        spec.callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_files",
                    Map.of(
                        AllotMintFilesTool.OPERATION,
                        "read",
                        AllotMintFilesTool.PATH,
                        "nonexistent.txt")));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .anyMatch(
            c ->
                c instanceof McpSchema.TextContent tc
                    && tc.text().contains("Not a file: nonexistent.txt"));
  }

  // ── operation: list ────────────────────────────────────────────────────

  @Test
  void listDirectoryReturnsEntries() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);
    McpSchema.CallToolResult result =
        spec.callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_files",
                    Map.of(AllotMintFilesTool.OPERATION, "list", AllotMintFilesTool.PATH, "")));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.structuredContent())
        .isInstanceOfSatisfying(
            Map.class,
            m -> {
              assertThat(m).containsEntry("path", ".");
              @SuppressWarnings("unchecked")
              List<Map<String, Object>> entries = (List<Map<String, Object>>) m.get("entries");
              assertThat(entries).extracting(e -> e.get("name")).contains("hello.txt", "subdir");
            });
  }

  @Test
  void listSubdirectory() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);
    McpSchema.CallToolResult result =
        spec.callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_files",
                    Map.of(
                        AllotMintFilesTool.OPERATION, "list", AllotMintFilesTool.PATH, "subdir")));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    @SuppressWarnings("unchecked")
    List<Map<String, Object>> entries = (List<Map<String, Object>>) structured.get("entries");
    assertThat(entries)
        .extracting(e -> e.get("name"))
        .containsExactlyInAnyOrder("a.txt", "b.txt", "deep.md");
  }

  @Test
  void listRejectsTraversalPath() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);
    assertThatThrownBy(
            () ->
                spec.callHandler()
                    .apply(
                        null,
                        new McpSchema.CallToolRequest(
                            "allotmint_files",
                            Map.of(
                                AllotMintFilesTool.OPERATION,
                                "list",
                                AllotMintFilesTool.PATH,
                                "../.."))))
        .isInstanceOf(McpFileAccessException.class)
        .hasMessageContaining("traversal");
  }

  // ── operation: search ──────────────────────────────────────────────────

  @Test
  void searchFindsMatches() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);
    McpSchema.CallToolResult result =
        spec.callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_files",
                    Map.of(
                        AllotMintFilesTool.OPERATION, "search",
                        AllotMintFilesTool.PATH, "",
                        AllotMintFilesTool.QUERY, "banana")));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    assertThat(structured).containsEntry("query", "banana");
    int matchCount = (int) structured.get("matchCount");
    assertThat(matchCount).isGreaterThanOrEqualTo(2); // in a.txt and deep.md
  }

  @Test
  void searchInSpecificDirectory() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);
    McpSchema.CallToolResult result =
        spec.callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_files",
                    Map.of(
                        AllotMintFilesTool.OPERATION, "search",
                        AllotMintFilesTool.PATH, "subdir",
                        AllotMintFilesTool.QUERY, "berry")));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    int matchCount = (int) structured.get("matchCount");
    assertThat(matchCount).isGreaterThanOrEqualTo(2); // blueberry, blackberry in b.txt
  }

  @Test
  void searchRequiresQuery() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);
    McpSchema.CallToolResult result =
        spec.callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_files",
                    Map.of(
                        AllotMintFilesTool.OPERATION, "search",
                        AllotMintFilesTool.PATH, "")));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .anyMatch(
            c ->
                c instanceof McpSchema.TextContent tc
                    && tc.text().contains("'query' argument is required"));
  }

  @Test
  void searchNoMatchesReturnsEmpty() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);
    McpSchema.CallToolResult result =
        spec.callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_files",
                    Map.of(
                        AllotMintFilesTool.OPERATION, "search",
                        AllotMintFilesTool.PATH, "",
                        AllotMintFilesTool.QUERY, "zzz_nonexistent_zzz")));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .anyMatch(
            c -> c instanceof McpSchema.TextContent tc && tc.text().contains("No matches found"));
    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    assertThat(structured).containsEntry("matchCount", 0);
  }

  @Test
  void searchRejectsTraversalPath() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);
    assertThatThrownBy(
            () ->
                spec.callHandler()
                    .apply(
                        null,
                        new McpSchema.CallToolRequest(
                            "allotmint_files",
                            Map.of(
                                AllotMintFilesTool.OPERATION, "search",
                                AllotMintFilesTool.PATH, "../etc",
                                AllotMintFilesTool.QUERY, "root"))))
        .isInstanceOf(McpFileAccessException.class)
        .hasMessageContaining("traversal");
  }

  // ── tool metadata ──────────────────────────────────────────────────────

  @Test
  void toolHasCorrectNameAndSchema() {
    McpServerFeatures.SyncToolSpecification spec = AllotMintFilesTool.specification(root);

    assertThat(spec.tool().name()).isEqualTo("allotmint_files");
    assertThat(spec.tool().description()).contains("Read", "list", "search");
    assertThat(spec.tool().inputSchema()).containsKey("properties");
  }
}
