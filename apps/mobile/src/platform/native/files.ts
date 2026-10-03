// App-private files: small JSON documents, the capture derivative transfer,
// and bounded authorized downloads. Upload bytes go only to allowlisted
// origins without the API credential; downloads carry the bearer credential
// only to API paths built by the shared client, land in private cache storage
// and are type/size checked before anything opens them.
import { ApiError, TransportError, checkUploadTarget, sha256Hex, type AuthorizedDownload, type UploadMediaType,
         type UploadTicket } from "@princess/api-client";
import { Directory, File, Paths, UploadType } from "expo-file-system";

import type { LocalFiles } from "../../work/capture-workflow.ts";
import type { AuthorizedFileClient, DownloadedFile, KeyValueFile } from "../contracts.ts";

const DOCUMENTS = "inktrospect";
const DOWNLOADS = "inktrospect-downloads";
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$/;

function dir(parent: Directory, name: string): Directory {
  const directory = new Directory(parent, name);
  if (!directory.exists) directory.create({ intermediates: true, idempotent: true });
  return directory;
}

export class ExpoDocumentStore implements KeyValueFile {
  async read(name: string): Promise<string | null> {
    if (!SAFE_NAME.test(name)) throw new Error("unsafe_document_name");
    const file = new File(dir(Paths.document, DOCUMENTS), name);
    return file.exists ? file.text() : null;
  }

  async write(name: string, value: string): Promise<void> {
    if (!SAFE_NAME.test(name)) throw new Error("unsafe_document_name");
    const folder = dir(Paths.document, DOCUMENTS);
    // Write then move, so a crash mid-write never leaves a truncated journal.
    const temp = new File(folder, `${name}.tmp`);
    if (temp.exists) temp.delete();
    temp.create();
    temp.write(value);
    temp.move(new File(folder, name), { overwrite: true });
  }

  async remove(name: string): Promise<void> {
    const file = new File(dir(Paths.document, DOCUMENTS), name);
    if (file.exists) file.delete();
  }
}

function statusFrom(message: string): number {
  const match = /\b([45]\d\d)\b/.exec(message);
  return match ? Number(match[1]) : 0;
}

export class ExpoLocalFiles implements LocalFiles {
  private readonly uploadOrigins: ReadonlySet<string>;

  constructor(uploadOrigins: ReadonlySet<string>) {
    this.uploadOrigins = uploadOrigins;
  }

  async digest(uri: string) {
    const file = new File(uri);
    if (!file.exists) return null;
    const bytes = await file.bytes();
    return { sha256: await sha256Hex(bytes), bytes: bytes.byteLength };
  }

  async upload(ticket: UploadTicket, uri: string, mediaType: UploadMediaType): Promise<void> {
    const url = checkUploadTarget(ticket, this.uploadOrigins);
    const file = new File(uri);
    if (!file.exists) throw new ApiError(0, "local_file_missing");
    let result: { status: number; body: string };
    try {
      // Streams the file natively; only the content type is sent, never the API credential.
      result = await file.upload(url, { httpMethod: "PUT", uploadType: UploadType.BINARY_CONTENT,
                                                   headers: { "content-type": mediaType }, sessionType: "foreground" });
    } catch {
      throw new TransportError("NETWORK");
    }
    if (result.status < 200 || result.status >= 300) {
      let code = "upload_failed";
      try {
        const raw = (JSON.parse(result.body) as { error?: unknown }).error;
        if (typeof raw === "string" && /^[a-z0-9_.:-]{1,64}$/.test(raw)) code = raw;
      } catch {
        // Storage providers answer in XML or not at all.
      }
      throw new ApiError(result.status, code);
    }
  }

  async remove(uri: string): Promise<void> {
    const file = new File(uri);
    if (file.exists) file.delete();
  }
}

function sniff(head: Uint8Array): string | null {
  if (head[0] === 0x25 && head[1] === 0x50 && head[2] === 0x44 && head[3] === 0x46) return "application/pdf";
  if (head[0] === 0x89 && head[1] === 0x50 && head[2] === 0x4e && head[3] === 0x47) return "image/png";
  if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) return "image/jpeg";
  return null;
}

export class ExpoAuthorizedFiles implements AuthorizedFileClient {
  private readonly apiBaseUrl: string;

  constructor(apiBaseUrl: string) {
    this.apiBaseUrl = apiBaseUrl.replace(/\/+$/, "");
  }

  async download(request: AuthorizedDownload, name: string,
                 limits: { readonly maxBytes: number; readonly mediaTypes: readonly string[] }): Promise<DownloadedFile> {
    if (!request.url.startsWith(`${this.apiBaseUrl}/v1/`)) throw new ApiError(0, "download_target_not_allowed");
    if (!SAFE_NAME.test(name)) throw new ApiError(0, "download_name_invalid");
    const target = new File(dir(Paths.cache, DOWNLOADS), name);
    if (target.exists) target.delete();
    let file: File;
    try {
      file = await File.downloadFileAsync(request.url, target, { headers: { ...request.headers }, idempotent: true });
    } catch (error) {
      if (target.exists) target.delete();
      const status = statusFrom(String((error as Error | null)?.message ?? ""));
      if (status > 0) throw new ApiError(status, status === 404 ? "not_found" : "download_failed");
      throw new TransportError("NETWORK");
    }
    const size = file.info().size ?? 0;
    const handle = file.open();
    let head: Uint8Array;
    try {
      head = handle.readBytes(8);
    } finally {
      handle.close();
    }
    const mediaType = sniff(head);
    if (size <= 0 || size > limits.maxBytes || mediaType === null || !limits.mediaTypes.includes(mediaType)) {
      file.delete();
      throw new ApiError(502, "download_out_of_bounds");
    }
    return { uri: file.uri, bytes: size, mediaType };
  }

  async remove(uri: string): Promise<void> {
    const file = new File(uri);
    if (file.exists) file.delete();
  }

  async sweep(maxAgeMs: number): Promise<number> {
    const now = Date.now();
    let removed = 0;
    for (const entry of dir(Paths.cache, DOWNLOADS).list()) {
      if (!(entry instanceof File)) continue;
      const info = entry.info();
      if (now - (info.modificationTime ?? 0) >= maxAgeMs) {
        entry.delete();
        removed += 1;
      }
    }
    return removed;
  }
}
