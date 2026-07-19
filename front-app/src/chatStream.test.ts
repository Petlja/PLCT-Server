import { describe, expect, test } from "vitest";
import { ChatEvent, readChatEvents } from "./chatStream";

describe("readChatEvents", () => {
    test("parses events split and combined across network chunks", async () => {
        const encoder = new TextEncoder();
        const bytes = encoder.encode(
            '{"type":"progress","stage":"retrieving","message":"Tražim sadržaj..."}\n' +
            '{"type":"content","text":"Prvi\\nred"}\n' +
            '{"type":"done"}'
        );
        const splitPoints = [7, 63, bytes.length - 5];
        const chunks = [
            bytes.slice(0, splitPoints[0]),
            bytes.slice(splitPoints[0], splitPoints[1]),
            bytes.slice(splitPoints[1], splitPoints[2]),
            bytes.slice(splitPoints[2]),
        ];
        const body = new ReadableStream<Uint8Array>({
            start(controller) {
                chunks.forEach(chunk => controller.enqueue(chunk));
                controller.close();
            },
        });
        const events: ChatEvent[] = [];

        await readChatEvents(
            new Response(body, { status: 200 }),
            event => events.push(event),
        );

        expect(events).toEqual([
            { type: "progress", stage: "retrieving", message: "Tražim sadržaj..." },
            { type: "content", text: "Prvi\nred" },
            { type: "done" },
        ]);
    });
});