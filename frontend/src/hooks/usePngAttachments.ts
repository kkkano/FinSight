import { useEffect, useRef, useState } from 'react';
import { assertAttachmentCount, readPngAttachment, type PngAttachment } from '../utils/pngAttachments';

/** 附件只在输入框内存中存在，晚到的读取结果不能穿越账号/会话。 */
export function usePngAttachments(sessionId: string, ownerId?: string | null) {
  const scope = JSON.stringify([ownerId || null, sessionId]);
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const generation = useRef(0);
  const [draft, setDraft] = useState<{ scope: string; items: PngAttachment[] }>({ scope, items: [] });
  const [reading, setReading] = useState(false);
  const [error, setError] = useState('');
  const attachments = draft.scope === scope ? draft.items : [];

  useEffect(() => {
    generation.current += 1;
    setDraft({ scope, items: [] });
    setReading(false);
    setError('');
  }, [scope]);
  useEffect(() => () => { generation.current += 1; }, []);

  const clear = () => {
    generation.current += 1;
    setDraft({ scope, items: [] });
    setReading(false);
    setError('');
  };
  const remove = (id: string) => {
    generation.current += 1;
    setDraft({ scope, items: attachments.filter((item) => item.id !== id) });
    setReading(false);
    setError('');
  };
  const add = async (files: File[]) => {
    if (!files.length || reading) return;
    const version = ++generation.current;
    setError('');
    try {
      assertAttachmentCount(attachments.length, files.length);
      setReading(true);
      const added = await Promise.all(files.map(readPngAttachment));
      if (generation.current !== version || scopeRef.current !== scope) return;
      setDraft({ scope, items: [...attachments, ...added] });
    } catch (failure) {
      if (generation.current === version && scopeRef.current === scope) {
        setError(failure instanceof Error ? failure.message : '图片读取失败，请重试。');
      }
    } finally {
      if (generation.current === version && scopeRef.current === scope) setReading(false);
    }
  };
  return { attachments, reading, error, add, remove, clear };
}

