/**
 * Incremental parser for the text/event-stream format
 * (https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation).
 *
 * Feed it decoded text chunks as they arrive; chunk boundaries can fall anywhere, including inside
 * a line or between "\r" and "\n". Comment lines (starting with ":", e.g. keep-alives) are ignored.
 */
export type SSEEvent = {
  event: string;
  data: string;
  id?: string;
  retry?: number;
};

export class SSEParser {
  private buffer = '';
  private data: string[] = [];
  private eventType = '';
  private lastId: string | undefined;
  private retry: number | undefined;
  private pendingCR = false;

  /** Add a chunk of text; returns the events completed by it. */
  push(chunk: string): SSEEvent[] {
    let text = chunk;
    if (this.pendingCR) {
      // A "\r\n" split across chunks: the "\r" already ended the line, skip the "\n".
      if (text.startsWith('\n')) text = text.slice(1);
      this.pendingCR = false;
    }
    this.buffer += text;
    const events: SSEEvent[] = [];
    let start = 0;
    for (let i = 0; i < this.buffer.length; i++) {
      const ch = this.buffer[i];
      if (ch !== '\n' && ch !== '\r') continue;
      const line = this.buffer.slice(start, i);
      if (ch === '\r') {
        if (i + 1 < this.buffer.length) {
          if (this.buffer[i + 1] === '\n') i++;
        } else {
          this.pendingCR = true;
        }
      }
      start = i + 1;
      const event = this.processLine(line);
      if (event) events.push(event);
    }
    this.buffer = this.buffer.slice(start);
    return events;
  }

  /** Call when the stream ends: dispatches a final event that lacked its trailing blank line. */
  flush(): SSEEvent[] {
    const events: SSEEvent[] = [];
    if (this.buffer.length > 0) {
      const event = this.processLine(this.buffer);
      if (event) events.push(event);
      this.buffer = '';
    }
    const last = this.dispatch();
    if (last) events.push(last);
    return events;
  }

  private processLine(line: string): SSEEvent | null {
    if (line === '') return this.dispatch();
    if (line.startsWith(':')) return null;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    switch (field) {
      case 'data':
        this.data.push(value);
        break;
      case 'event':
        this.eventType = value;
        break;
      case 'id':
        if (!value.includes('\0')) this.lastId = value;
        break;
      case 'retry':
        if (/^\d+$/.test(value)) this.retry = Number(value);
        break;
      default:
        break;
    }
    return null;
  }

  private dispatch(): SSEEvent | null {
    if (this.data.length === 0) {
      this.eventType = '';
      return null;
    }
    const event: SSEEvent = { event: this.eventType || 'message', data: this.data.join('\n') };
    if (this.lastId !== undefined) event.id = this.lastId;
    if (this.retry !== undefined) event.retry = this.retry;
    this.data = [];
    this.eventType = '';
    return event;
  }
}
