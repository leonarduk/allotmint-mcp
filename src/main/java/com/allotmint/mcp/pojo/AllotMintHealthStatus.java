package com.allotmint.mcp.pojo;

import com.allotmint.mcp.client.AllotMintClient;

/**
 * Result of an {@link AllotMintClient#health()} call.
 *
 * @param reachable whether the backend responded successfully
 * @param version backend version string, if the backend reports one
 * @param baseUrl the base URL that was called
 */
public record AllotMintHealthStatus(boolean reachable, String version, String baseUrl) {}
