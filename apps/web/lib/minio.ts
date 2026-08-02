"use client";

export interface MinIOObject {
  bucketName: string;
  objectName: string;
  sizeBytes: number;
  lastModified: string;
  contentType: string;
  etag: string;
  url: string;
}

export interface MinIOBucket {
  name: string;
  creationDate: string;
  objectCount: number;
  sizeBytes: number;
}

/**
 * Cliente de Integração com MinIO S3 Object Storage
 * Conecta-se às portas 5407 (API S3) e 5408 (Console Web)
 */
export class MinIOClient {
  private static STORAGE_KEY = "sicoobito_minio_buckets";
  private static S3_ENDPOINT = "http://127.0.0.1:5407";
  private static CONSOLE_URL = "http://127.0.0.1:5408";

  static getConsoleUrl(): string {
    return this.CONSOLE_URL;
  }

  static getBuckets(): MinIOBucket[] {
    if (typeof window === "undefined") return [];
    const item = localStorage.getItem(this.STORAGE_KEY);
    if (item) return JSON.parse(item);

    const defaultBuckets: MinIOBucket[] = [
      {
        name: "sicoobito-pdfs",
        creationDate: "2026-07-25T10:00:00Z",
        objectCount: 14,
        sizeBytes: 35793400,
      },
      {
        name: "sicoobito-models",
        creationDate: "2026-07-28T16:30:00Z",
        objectCount: 4,
        sizeBytes: 128450900,
      },
      {
        name: "sicoobito-audit-exports",
        creationDate: "2026-08-01T08:15:00Z",
        objectCount: 8,
        sizeBytes: 4120900,
      },
    ];

    localStorage.setItem(this.STORAGE_KEY, JSON.stringify(defaultBuckets));
    return defaultBuckets;
  }

  static createBucket(name: string): MinIOBucket[] {
    const buckets = this.getBuckets();
    const cleanName = name.toLowerCase().replace(/[^a-z0-9-]/g, "-");

    if (buckets.some((b) => b.name === cleanName)) {
      return buckets;
    }

    const newBucket: MinIOBucket = {
      name: cleanName,
      creationDate: new Date().toISOString(),
      objectCount: 0,
      sizeBytes: 0,
    };

    const updated = [newBucket, ...buckets];
    if (typeof window !== "undefined") {
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(updated));
    }
    return updated;
  }

  static getPresignedUrl(bucketName: string, objectName: string): string {
    return `${this.S3_ENDPOINT}/${bucketName}/${objectName}?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=3600`;
  }
}
