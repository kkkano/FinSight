import { describe, expect, it } from 'vitest';
import { assertAttachmentCount, assertPngFile, MAX_PNG_BYTES, pngDimensions } from './pngAttachments';

function pngHeader(width: number, height: number): ArrayBuffer {
  const header = new Uint8Array(24);
  header.set([137, 80, 78, 71, 13, 10, 26, 10]);
  const view = new DataView(header.buffer);
  view.setUint32(8, 13);
  header.set([73, 72, 68, 82], 12);
  view.setUint32(16, width);
  view.setUint32(20, height);
  return header.buffer;
}

describe('PNG current-turn attachment boundaries', () => {
  it('accepts exactly three files and rejects an accumulated fourth', () => {
    expect(() => assertAttachmentCount(1, 2)).not.toThrow();
    expect(() => assertAttachmentCount(2, 2)).toThrow('最多添加 3');
  });
  it('accepts the 2MiB byte boundary but rejects larger or empty files', () => {
    expect(() => assertPngFile({ type: 'image/png', size: MAX_PNG_BYTES, name: '图.png' })).not.toThrow();
    expect(() => assertPngFile({ type: 'image/png', size: MAX_PNG_BYTES + 1, name: '图.png' })).toThrow('2 MiB');
    expect(() => assertPngFile({ type: 'image/png', size: 0, name: '图.png' })).toThrow('为空');
  });
  it.each(['image/jpeg', 'image/svg+xml', 'text/html'])('rejects %s regardless of its filename', (type) => {
    expect(() => assertPngFile({ type, size: 100, name: 'fake.png' })).toThrow('仅支持 PNG');
  });
  it('accepts eight million pixels and rejects a larger image before decoding', () => {
    expect(pngDimensions(pngHeader(4000, 2000))).toEqual({ width: 4000, height: 2000 });
    expect(() => pngDimensions(pngHeader(4001, 2000))).toThrow('800 万像素');
  });
  it('rejects forged file contents and zero dimensions', () => {
    expect(() => pngDimensions(new Uint8Array(24).buffer)).toThrow('不是有效的 PNG');
    expect(() => pngDimensions(pngHeader(0, 2000))).toThrow('尺寸无效');
    expect(() => pngDimensions(pngHeader(8193, 1))).toThrow('8192');
    const forged = pngHeader(1, 1);
    new DataView(forged).setUint32(8, 12);
    expect(() => pngDimensions(forged)).toThrow('图片头无效');
  });
});

