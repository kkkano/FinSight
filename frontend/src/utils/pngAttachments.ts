import type { ChatImageInput } from '../types/runtime';
import { researchFailureMessage } from './researchFailure';

export class PngAttachmentError extends Error {
  readonly code: string;
  constructor(code: string) { super(researchFailureMessage({ error_code: code })); this.code = code; }
}

export const MAX_PNG_ATTACHMENTS = 3;
export const MAX_PNG_BYTES = 2 * 1024 * 1024;
export const MAX_PNG_PIXELS = 8_000_000;

export interface PngAttachment extends ChatImageInput {
  id: string;
  name: string;
  width: number;
  height: number;
  byteSize: number;
}

export function assertPngFile(file: Pick<File, 'type' | 'size' | 'name'>): void {
  if (file.type !== 'image/png') throw new PngAttachmentError('png_type');
  if (!file.size) throw new PngAttachmentError('png_empty');
  if (file.size > MAX_PNG_BYTES) throw new PngAttachmentError('png_size');
}

export function assertAttachmentCount(existing: number, incoming: number): void {
  if (existing + incoming > MAX_PNG_ATTACHMENTS) throw new PngAttachmentError('png_count');
}

/** 在浏览器解码前读取固定大小的PNG头，先拒绝超大像素图。 */
export function pngDimensions(header: ArrayBuffer): { width: number; height: number } {
  const bytes = new Uint8Array(header);
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (bytes.length < 24 || signature.some((byte, i) => bytes[i] !== byte)
    || bytes[12] !== 73 || bytes[13] !== 72 || bytes[14] !== 68 || bytes[15] !== 82) {
    throw new PngAttachmentError('png_invalid');
  }
  const view = new DataView(header);
  if (view.getUint32(8) !== 13) throw new PngAttachmentError('png_header');
  const width = view.getUint32(16);
  const height = view.getUint32(20);
  if (!width || !height) throw new PngAttachmentError('png_dimensions');
  if (Math.max(width, height) > 8192) throw new PngAttachmentError('png_side');
  if (width * height > MAX_PNG_PIXELS) throw new PngAttachmentError('png_pixels');
  return { width, height };
}

function asDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new PngAttachmentError('png_read'));
    reader.onabort = () => reject(new PngAttachmentError('request_cancelled'));
    reader.onload = () => {
      if (typeof reader.result !== 'string' || !reader.result.startsWith('data:image/png;base64,')) {
        reject(new PngAttachmentError('png_encoding'));
      } else resolve(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

function verifyImage(dataUrl: string, width: number, height: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      if (image.naturalWidth !== width || image.naturalHeight !== height) reject(new PngAttachmentError('png_mismatch'));
      else resolve();
    };
    image.onerror = () => reject(new PngAttachmentError('png_decode'));
    image.src = dataUrl;
  });
}

export async function readPngAttachment(file: File): Promise<PngAttachment> {
  assertPngFile(file);
  const { width, height } = pngDimensions(await file.slice(0, 24).arrayBuffer());
  const data_url = await asDataUrl(file);
  await verifyImage(data_url, width, height);
  return {
    id: crypto.randomUUID(), name: Array.from(file.name).filter((character) => character.charCodeAt(0) >= 32).join('').slice(0, 128),
    data_url, width, height, byteSize: file.size,
  };
}

