/**
 * Cliente frontend para as operações do Firecrawl (scrape, search, crawl, ingestão RAG).
 */

import { get, post } from "@/lib/client";

export interface FirecrawlScrapeResponse {
  ok: boolean;
  data: {
    markdown?: string;
    html?: string;
    rawHtml?: string;
    metadata?: {
      title?: string;
      description?: string;
      sourceURL?: string;
      statusCode?: number;
      ogTitle?: string;
      ogDescription?: string;
      [key: string]: unknown;
    };
    links?: string[];
  };
}

export interface FirecrawlSearchResultItem {
  title?: string;
  url?: string;
  description?: string;
  markdown?: string;
  [key: string]: unknown;
}

export interface FirecrawlSearchResponse {
  ok: boolean;
  results: FirecrawlSearchResultItem[];
}

export interface FirecrawlMapResponse {
  ok: boolean;
  links: string[];
}

export interface FirecrawlCrawlJobResponse {
  ok: boolean;
  data: {
    id?: string;
    url?: string;
    status?: "scraping" | "completed" | "failed" | "cancelled";
    total?: number;
    completed?: number;
    creditsUsed?: number;
    expiresAt?: string;
    data?: Array<{
      markdown?: string;
      metadata?: {
        title?: string;
        sourceURL?: string;
        [key: string]: unknown;
      };
    }>;
    [key: string]: unknown;
  };
}

export interface FirecrawlIngestResponse {
  ok: boolean;
  result: {
    document_id?: string;
    filename?: string;
    url?: string;
    chunk_count?: number;
    status?: string;
    crawl_id?: string;
    pages_indexed?: number;
    total_chunks?: number;
    documents?: Array<{
      document_id: string;
      filename: string;
      url: string;
      chunk_count: number;
    }>;
  };
}

export async function scrapeUrl(
  url: string,
  onlyMainContent = true,
  waitFor = 0,
): Promise<FirecrawlScrapeResponse> {
  return post<FirecrawlScrapeResponse>("/api/firecrawl/scrape", {
    url,
    only_main_content: onlyMainContent,
    wait_for: waitFor,
  });
}

export async function searchWeb(
  query: string,
  limit = 5,
): Promise<FirecrawlSearchResponse> {
  return post<FirecrawlSearchResponse>("/api/firecrawl/search", {
    query,
    limit,
  });
}

export async function mapSite(
  url: string,
  search?: string,
  limit = 100,
): Promise<FirecrawlMapResponse> {
  return post<FirecrawlMapResponse>("/api/firecrawl/map", {
    url,
    search: search || undefined,
    limit,
  });
}

export async function startCrawl(
  url: string,
  maxDepth = 2,
  limit = 10,
  includePaths?: string[],
  excludePaths?: string[],
): Promise<{ ok: boolean; data: { id: string; url: string } }> {
  return post<{ ok: boolean; data: { id: string; url: string } }>("/api/firecrawl/crawl", {
    url,
    max_depth: maxDepth,
    limit,
    include_paths: includePaths || undefined,
    exclude_paths: excludePaths || undefined,
  });
}

export async function getCrawlStatus(crawlId: string): Promise<FirecrawlCrawlJobResponse> {
  return get<FirecrawlCrawlJobResponse>(`/api/firecrawl/crawl/${encodeURIComponent(crawlId)}`);
}

export async function ingestWeb(options: {
  url: string;
  project?: string | null;
  crawl?: boolean;
  maxDepth?: number;
  limit?: number;
}): Promise<FirecrawlIngestResponse> {
  return post<FirecrawlIngestResponse>("/api/firecrawl/ingest", {
    url: options.url,
    project: options.project || undefined,
    crawl: Boolean(options.crawl),
    max_depth: options.maxDepth ?? 2,
    limit: options.limit ?? 10,
  });
}
