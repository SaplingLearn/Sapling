import { redirect } from "next/navigation";

export default function FlashcardsPage() {
  redirect("/study?mode=cards");
}
