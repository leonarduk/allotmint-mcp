package com.allotmint.mcp;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

/**
 * The {@code allotmint_files} tool: read, list, and search files within a directory whose root is
 * set by {@code ALLOTMINT_MCP_FILES_ROOT}, gated behind {@code ALLOTMINT_MCP_FILES_ENABLED}.
 *
 * <p>All path arguments are resolved relative to the configured root. Path traversal (e.g. {@code
 * ../../etc/passwd}, absolute paths outside root, symlink escapes) is rejected via resolved-path
 * containment rather than string prefix matching.
 *
 * <p>Write operations are out of scope for this tool (see issue #10).
 */
final class AllotMintFilesTool {

  static final String OPERATION = "operation";
  static final String PATH = "path";
  static final String QUERY = "query";

  private static final Map<String, Object> INPUT_SCHEMA =
      Map.of(
          "type", "object",
          "properties",
              Map.of(
                  OPERATION, Map.of("type", "string", "enum", List.of("read", "list", "search")),
                  PATH,
                      Map.of(
                          "type", "string",
                          "description",
                              "File or directory path relative to the files root. Defaults to the root itself."),
                  QUERY,
                      Map.of(
                          "type", "string",
                          "description",
                              "Search term for the 'search' operation. Required for search.")),
          "required", List.of(OPERATION));

  private AllotMintFilesTool() {}

  static McpServerFeatures.SyncToolSpecification specification(Path filesRoot) {
    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_files", INPUT_SCHEMA)
            .description(
                "Read, list, and search files within the configured files root directory."
                    + " Operations: 'read' reads a file, 'list' lists directory contents,"
                    + " 'search' searches file contents recursively for a query string.")
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler(
            (exchange, request) -> {
              String operation = String.valueOf(request.arguments().get(OPERATION));
              String pathArg =
                  request.arguments().get(PATH) != null
                      ? String.valueOf(request.arguments().get(PATH))
                      : "";
              String query =
                  request.arguments().get(QUERY) != null
                      ? String.valueOf(request.arguments().get(QUERY))
                      : null;

              return switch (operation) {
                case "read" -> handleRead(filesRoot, pathArg);
                case "list" -> handleList(filesRoot, pathArg);
                case "search" -> handleSearch(filesRoot, pathArg, query);
                default -> errorResult("Unknown operation: " + operation);
              };
            })
        .build();
  }

  // ── handlers ──────────────────────────────────────────────────────────

  private static McpSchema.CallToolResult handleRead(Path root, String pathArg) {
    Path file = resolveAndValidate(root, pathArg);
    if (!Files.isRegularFile(file)) {
      return errorResult("Not a file: " + pathArg);
    }
    try {
      String content = Files.readString(file);
      Map<String, Object> structured = new LinkedHashMap<>();
      structured.put("path", pathArg);
      structured.put("size", content.length());
      return McpSchema.CallToolResult.builder()
          .addTextContent(content)
          .structuredContent(structured)
          .build();
    } catch (IOException e) {
      return errorResult("Failed to read file: " + e.getMessage());
    }
  }

  private static McpSchema.CallToolResult handleList(Path root, String pathArg) {
    Path dir = resolveAndValidate(root, pathArg);
    if (!Files.isDirectory(dir)) {
      return errorResult("Not a directory: " + pathArg);
    }
    try (Stream<Path> entries = Files.list(dir)) {
      List<Map<String, Object>> listing = new ArrayList<>();
      entries
          .sorted()
          .forEach(
              p -> {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("name", p.getFileName().toString());
                entry.put("type", Files.isDirectory(p) ? "directory" : "file");
                try {
                  entry.put("size", Files.size(p));
                } catch (IOException ignored) {
                  entry.put("size", -1L);
                }
                listing.add(entry);
              });

      StringBuilder text = new StringBuilder();
      for (Map<String, Object> e : listing) {
        text.append(e.get("type"))
            .append('\t')
            .append(e.get("name"))
            .append('\t')
            .append(e.get("size"))
            .append('\n');
      }

      Map<String, Object> structured = new LinkedHashMap<>();
      structured.put("path", pathArg.isEmpty() ? "." : pathArg);
      structured.put("entries", listing);

      return McpSchema.CallToolResult.builder()
          .addTextContent(text.toString().stripTrailing())
          .structuredContent(structured)
          .build();
    } catch (IOException e) {
      return errorResult("Failed to list directory: " + e.getMessage());
    }
  }

  private static McpSchema.CallToolResult handleSearch(Path root, String pathArg, String query) {
    if (query == null || query.isBlank()) {
      return errorResult("The 'query' argument is required for the 'search' operation");
    }
    Path searchDir = root;
    if (!pathArg.isEmpty()) {
      searchDir = resolveAndValidate(root, pathArg);
      if (!Files.isDirectory(searchDir)) {
        return errorResult("Not a directory: " + pathArg);
      }
    }

    List<Map<String, Object>> matches = new ArrayList<>();
    try (Stream<Path> walk = Files.walk(searchDir)) {
      walk.filter(Files::isRegularFile)
          .filter(
              f -> {
                try {
                  return Files.size(f) < 1_048_576; // skip files > 1 MB
                } catch (IOException ignored) {
                  return false;
                }
              })
          .forEach(
              file -> {
                try {
                  String content = Files.readString(file);
                  int lineNum = 0;
                  for (String line : content.lines().toList()) {
                    lineNum++;
                    if (line.contains(query)) {
                      Map<String, Object> match = new LinkedHashMap<>();
                      match.put("file", root.relativize(file).toString().replace('\\', '/'));
                      match.put("line", lineNum);
                      match.put("content", line.stripTrailing());
                      matches.add(match);
                    }
                  }
                } catch (IOException ignored) {
                  // skip unreadable files
                }
              });
    } catch (IOException e) {
      return errorResult("Failed to search: " + e.getMessage());
    }

    StringBuilder text = new StringBuilder();
    for (Map<String, Object> m : matches) {
      text.append(m.get("file"))
          .append(':')
          .append(m.get("line"))
          .append(": ")
          .append(m.get("content"))
          .append('\n');
    }

    Map<String, Object> structured = new LinkedHashMap<>();
    structured.put("query", query);
    structured.put("path", pathArg.isEmpty() ? "." : pathArg);
    structured.put("matchCount", matches.size());
    structured.put("matches", matches);

    return McpSchema.CallToolResult.builder()
        .addTextContent(
            text.isEmpty() ? "No matches found for: " + query : text.toString().stripTrailing())
        .structuredContent(structured)
        .build();
  }

  // ── path validation ───────────────────────────────────────────────────

  /**
   * Resolves {@code relativePath} against {@code root} and validates that the result is strictly
   * within the root directory. Uses resolved-path containment (not string prefix matching):
   *
   * <ol>
   *   <li>If the resolved path exists, its {@link Path#toRealPath() real path} is checked against
   *       the root's real path.
   *   <li>If the resolved path does not exist, we walk up the parent chain to find the nearest
   *       existing ancestor, resolve it to its real path, and check containment.
   * </ol>
   *
   * @throws McpFileAccessException if the path escapes the root directory
   */
  static Path resolveAndValidate(Path root, String relativePath) {
    Path resolvedRoot = root.toAbsolutePath().normalize();
    // resolve("") returns the root itself, which is fine
    Path resolved = resolvedRoot.resolve(relativePath).toAbsolutePath().normalize();

    try {
      Path realRoot = resolvedRoot.toRealPath();
      Path realResolved = resolved.toRealPath();
      if (!realResolved.startsWith(realRoot)) {
        throw new McpFileAccessException(
            "Path traversal rejected: '" + relativePath + "' escapes the files root");
      }
      return realResolved;
    } catch (NoSuchFileException e) {
      // The target doesn't exist yet — walk up to the nearest existing ancestor.
      Path nearest = resolved;
      while (nearest != null && !Files.exists(nearest)) {
        nearest = nearest.getParent();
      }
      if (nearest == null) {
        throw new McpFileAccessException("Cannot resolve path: " + relativePath);
      }
      try {
        Path realRoot = resolvedRoot.toRealPath();
        Path realNearest = nearest.toRealPath();
        if (!realNearest.startsWith(realRoot)) {
          throw new McpFileAccessException(
              "Path traversal rejected: '" + relativePath + "' escapes the files root");
        }
      } catch (IOException ioe) {
        throw new McpFileAccessException("Failed to validate path: " + ioe.getMessage());
      }
      return resolved;
    } catch (IOException e) {
      throw new McpFileAccessException("Failed to resolve path: " + e.getMessage());
    }
  }

  private static McpSchema.CallToolResult errorResult(String message) {
    return McpSchema.CallToolResult.builder().isError(true).addTextContent(message).build();
  }
}
