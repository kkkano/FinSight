import type { ChatImageInput } from '../types/runtime';

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
  if (file.type !== 'image/png') throw new Error('仅支持 PNG 图片，请先转换为 PNG。');
  if (!file.size) throw new Error('图片文件为空，请重新选择。');
  if (file.size > MAX_PNG_BYTES) throw new Error('每张 PNG 图片不能超过 2 MiB。');
}

export function assertAttachmentCount(existing: number, incoming: number): void {
  if (existing + incoming > MAX_PNG_ATTACHMENTS) throw new Error('每轮最多添加 3 张 PNG 图片。');
}

/** 在浏览器解码前读取固定大小的PNG头，先拒绝超大像素图。 */
export function pngDimensions(header: ArrayBuffer): { width: number; height: number } {
  const bytes = new Uint8Array(header);
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (bytes.length < 24 || signature.some((byte, i) => bytes[i] !== byte)
    || bytes[12] !== 73 || bytes[13] !== 72 || bytes[14] !== 68 || bytes[15] !== 82) {
    throw new Error('文件内容不是有效的 PNG 图片。');
  }
  const view = new DataView(header);
  if (view.getUint32(8) !== 13) throw new Error('PNG 图片头无效，请重新导出图片。');
  const width = view.getUint32(16);
  const height = view.getUint32(20);
  if (!width || !height) throw new Error('图片尺寸无效。');
  if (Math.max(width, height) > 8192) throw new Error('PNG 图片单边不能超过 8192 像素。');
  if (width * height > MAX_PNG_PIXELS) throw new Error('每张 PNG 图片不能超过 800 万像素。');
  return { width, height };
}

function asDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('图片读取失败，请重新选择。'));
    reader.onabort = () => reject(new Error('图片读取已取消。'));
    reader.onload = () => {
      if (typeof reader.result !== 'string' || !reader.result.startsWith('data:image/png;base64,')) {
        reject(new Error('图片编码无效，请重新选择 PNG。'));
      } else resolve(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

function verifyImage(dataUrl: string, width: number, height: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      if (image.naturalWidth !== width || image.naturalHeight !== height) reject(new Error('PNG 图片尺寸与内容不一致。'));
      else resolve();
    };
    image.onerror = () => reject(new Error('PNG 图片无法解码，请重新导出后再试。'));
    image.src = dataUrl;
  });
}

export async function readPngAttachment(file: File): Promise<PngAttachment> {
  assertPngFile(file);
  const { width, height } = pngDimensions(await file.slice(0, 24).arrayBuffer());
  const data_url = await asDataUrl(file);
  await verifyImage(data_url, width, height);
  return {
    id: crypto.randomUUID(), name: file.name.replace(/[\u0000-\u001f]/g, '').slice(0, 128),
    data_url, width, height, byteSize: file.size,
  };
}

