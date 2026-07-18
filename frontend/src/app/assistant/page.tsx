import { redirect } from "next/navigation";

// The AI assistant is now the main screen. Keep this path working.
export default function AssistantRedirect() {
  redirect("/home");
}
