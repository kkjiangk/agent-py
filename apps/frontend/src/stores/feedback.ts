import { defineStore } from "pinia";

export type FeedbackKind = "error" | "info" | "success";

export interface FeedbackMessage {
  readonly id: number;
  readonly kind: FeedbackKind;
  readonly message: string;
}

export const useFeedbackStore = defineStore("feedback", {
  state: () => ({
    current: null as FeedbackMessage | null,
    nextId: 1
  }),
  actions: {
    dismiss(): void {
      this.current = null;
    },
    show(kind: FeedbackKind, message: string): void {
      this.current = { id: this.nextId, kind, message };
      this.nextId += 1;
    },
    showError(message: string): void {
      this.show("error", message);
    }
  }
});
