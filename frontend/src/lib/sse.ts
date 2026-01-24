/**
 * Minimal Server-Sent Events (SSE) parser for fetch() responses.
 *
 * We use this instead of EventSource because we need a POST request body.
 */
export async function* parseSseDataFrames(
  response: Response,
): AsyncGenerator<string> {
  const body = response.body;
  if (!body) {
    throw new Error("Streaming response body was empty.");
  }

  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    while (true) {
      const frameEnd = buffer.indexOf("\n\n");
      if (frameEnd === -1) break;

      const rawFrame = buffer.slice(0, frameEnd);
      buffer = buffer.slice(frameEnd + 2);

      // Collect all `data:` lines and join with '\n' per SSE spec.
      const dataLines: string[] = [];
      for (const line of rawFrame.split("\n")) {
        if (line.startsWith("data:")) {
          dataLines.push(line.slice("data:".length).trimStart());
        }
      }

      if (dataLines.length === 0) continue;
      yield dataLines.join("\n");
    }
  }
}

