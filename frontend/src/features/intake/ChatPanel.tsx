import { useEffect, useRef, useState } from "react";
import { FOCUS_CHAT_EVENT, useShop } from "../shop/ShopContext";
import "./intake.css";

const BASKET_PROMPTS = ["Replace the lentils with chicken", "Make it $5 cheaper", "Why did you pick these?", "Plan my meals", "Which store is cheapest?"];

/** Conversation with the AI Personal Shopper. Every message goes through supervisor routing (/chat). */
export default function ChatPanel() {
  const { state, chat, busy, pendingMessage } = useShop();
  const [text, setText] = useState("");
  const listRef = useRef<HTMLOListElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messages = state?.chat ?? [];

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, pendingMessage]);

  // Other panels can ask for the chat ("Change by chatting"); "/" focuses it from anywhere.
  useEffect(() => {
    const focus = (prefill?: string) => {
      if (prefill) setText((t) => t || prefill);
      requestAnimationFrame(() => inputRef.current?.focus());
    };
    const onFocusEvent = (e: Event) => focus((e as CustomEvent<string | undefined>).detail);
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) && !target.isContentEditable) {
        e.preventDefault();
        focus();
      }
    };
    window.addEventListener(FOCUS_CHAT_EVENT, onFocusEvent);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener(FOCUS_CHAT_EVENT, onFocusEvent);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  async function send(value: string) {
    const v = value.trim();
    if (!v || busy) return;
    setText("");
    await chat(v);
  }

  const hasBasket = !!state?.basket;
  return (
    <div className="chat">
      <header className="chat-head">
        <span className="chat-avatar" aria-hidden="true">TM</span>
        <div>
          <strong>Your personal shopper</strong>
          <p className="small muted">
            Describe your shop or ask for changes. Press <kbd>/</kbd> to type.
          </p>
        </div>
      </header>

      <ol className="chat-list" ref={listRef} aria-live="polite">
        {messages.length === 0 && !pendingMessage && (
          <li className="bubble assistant">
            Hi! Tell me your budget, how many meals, for how many days, and anything you can't eat. I'll build a basket that
            fits — and show you why.
          </li>
        )}
        {messages.map((m, i) => (
          <li key={i} className={`bubble ${m.role}`}>
            {m.text}
          </li>
        ))}
        {pendingMessage && <li className="bubble user pending">{pendingMessage}</li>}
        {pendingMessage && busy && (
          <li className="bubble assistant typing" aria-label="Shopper is typing">
            <span />
            <span />
            <span />
          </li>
        )}
      </ol>

      {hasBasket && (
        <div className="chat-suggestions">
          {BASKET_PROMPTS.map((p) => (
            <button key={p} className="chip" onClick={() => send(p)} disabled={!!busy}>
              {p}
            </button>
          ))}
        </div>
      )}

      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          void send(text);
        }}
      >
        <label className="sr-only" htmlFor="chat-text">
          Message your shopper
        </label>
        <textarea
          ref={inputRef}
          id="chat-text"
          className="input"
          rows={2}
          placeholder={hasBasket ? "e.g. swap the rice for pasta" : "e.g. $90 for the week, dinners for two, no nuts"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(text);
            }
          }}
        />
        <button className="btn btn-primary" disabled={!text.trim() || !!busy}>
          Send
        </button>
      </form>
    </div>
  );
}
