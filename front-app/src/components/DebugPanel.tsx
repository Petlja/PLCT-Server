import { useEffect, useRef } from "react";
import { DebugEvent } from "../chatStream";

/** The log keeps running across questions, so each run is announced by the question
 *  that started it -- `elapsed` counts from zero again on every request. */
export type DebugLine = DebugEvent | { type: "question"; text: string };

/** Enough to hold a long session, short enough that the panel stays a panel. */
export const MAX_DEBUG_LINES = 2000;

export function appendDebug(lines: DebugLine[], line: DebugLine): DebugLine[] {
    const appended = [...lines, line];
    return appended.length > MAX_DEBUG_LINES
        ? appended.slice(appended.length - MAX_DEBUG_LINES)
        : appended;
}

/** What the server logged while answering, in the order it logged it. */
export function DebugPanel({ lines, onClear }: {
    lines: DebugLine[];
    onClear: () => void;
}) {
    const endRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        endRef.current?.scrollIntoView({ block: "nearest" });
    }, [lines.length]);

    return (
        <div className="debug-panel">
            <div className="debug-header">
                <span>Dnevnik obrade</span>
                <button type="button" onClick={onClear} disabled={lines.length === 0}>
                    Obriši
                </button>
            </div>
            <div className="debug-lines">
                {lines.length === 0
                    ? <p className="debug-empty">Dnevnik je prazan &mdash; postavi pitanje.</p>
                    : lines.map((line, i) => (line.type === "question"
                        ? <div className="debug-question" key={i}>{line.text}</div>
                        : (
                            <div
                                className={`debug-line debug-${line.level.toLowerCase()}`
                                    + (line.source === "ui" ? " debug-ui" : "")}
                                key={i}
                            >
                                <span className="debug-elapsed">{line.elapsed.toFixed(2)}s</span>
                                <span className="debug-source">{line.source}</span>
                                <span className="debug-message">{line.message}</span>
                            </div>
                        )))}
                <div ref={endRef} />
            </div>
        </div>
    );
}
