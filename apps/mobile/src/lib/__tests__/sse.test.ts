import { describe, expect, it } from '@jest/globals';

import { parseChatEvent } from '../chat-events';
import { SSEParser } from '../sse';

function parseAll(chunks: string[]) {
  const parser = new SSEParser();
  const events = chunks.flatMap((chunk) => parser.push(chunk));
  return [...events, ...parser.flush()];
}

describe('SSEParser', () => {
  it('parses complete events', () => {
    const events = parseAll(['data: {"type":"text","delta":"Hi"}\n\n', 'data: {"type":"done","message_id":1}\n\n']);
    expect(events.map((e) => e.data)).toEqual(['{"type":"text","delta":"Hi"}', '{"type":"done","message_id":1}']);
    expect(events[0].event).toBe('message');
  });

  it('handles lines split across chunks', () => {
    const events = parseAll(['da', 'ta: {"type":"te', 'xt","delta":"Hel', 'lo"}\n', '\n']);
    expect(events).toHaveLength(1);
    expect(JSON.parse(events[0].data)).toEqual({ type: 'text', delta: 'Hello' });
  });

  it('handles CRLF and a CR at a chunk boundary', () => {
    const events = parseAll(['data: a\r', '\ndata: b\r\n\r', '\n']);
    expect(events).toEqual([{ event: 'message', data: 'a\nb' }]);
  });

  it('ignores comments and keep-alives', () => {
    const events = parseAll([': ping\n\n', ':\n', 'data: x\n\n']);
    expect(events.map((e) => e.data)).toEqual(['x']);
  });

  it('reads event, id and retry fields', () => {
    const events = parseAll(['event: update\nid: 7\nretry: 1500\ndata: y\n\n']);
    expect(events).toEqual([{ event: 'update', data: 'y', id: '7', retry: 1500 }]);
  });

  it('strips only one leading space from values', () => {
    expect(parseAll(['data:  two spaces\n\n'])[0].data).toBe(' two spaces');
    expect(parseAll(['data:none\n\n'])[0].data).toBe('none');
  });

  it('dispatches a final event without a trailing blank line on flush', () => {
    expect(parseAll(['data: last']).map((e) => e.data)).toEqual(['last']);
  });

  it('skips events with no data', () => {
    expect(parseAll(['event: noop\n\n'])).toEqual([]);
  });

  it('survives a chunk per character', () => {
    const payload = 'data: {"type":"text","delta":"ok"}\r\n\r\n';
    expect(parseAll(payload.split(''))).toHaveLength(1);
  });
});

describe('parseChatEvent', () => {
  it('accepts known event types', () => {
    expect(parseChatEvent('{"type":"tool","name":"create_goal","status":"started","label":"Creating"}')).toEqual({
      type: 'tool',
      name: 'create_goal',
      status: 'started',
      label: 'Creating',
    });
  });

  it('rejects unknown types and invalid JSON', () => {
    expect(parseChatEvent('{"type":"mystery"}')).toBeNull();
    expect(parseChatEvent('not json')).toBeNull();
  });
});
