import Link from "next/link";

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-[#F4F7F5] flex flex-col">
      <div className="flex-1 max-w-3xl mx-auto px-8 py-16 w-full">
        <div className="flex items-center gap-2 mb-12">
          <Link href="/" className="text-sm text-gray-500 hover:text-gray-900 transition-colors">
            ← Back to Sapling
          </Link>
        </div>

        <h1 className="text-4xl font-semibold text-gray-900 mb-8">About Sapling</h1>

        <div className="prose prose-gray max-w-none space-y-6 text-gray-600 leading-relaxed">
          <p>
            <strong className="text-gray-900">Sapling</strong> is an AI-powered study companion built by students, for students. We believe that learning shouldn't be passive — it should adapt to you, challenge you, and show you exactly where you stand.
          </p>

          <p>
            At its core, Sapling maps your understanding as a live knowledge graph that grows with every session, quiz, and document you interact with. Paired with an AI tutor that can reason with you Socratically, explain concepts directly, or flip the table and have you teach back, Sapling meets you wherever you are in your learning journey.
          </p>

          <p>
            Sapling was born out of a hackathon and built by a team of four students who were frustrated with static study tools that don't actually know what you know. We wanted something that feels less like a flashcard app and more like a study partner who's always prepared.
          </p>

          <div>
            <p className="font-medium text-gray-900 mb-3">What makes Sapling different:</p>
            <ul className="space-y-2 list-none pl-0">
              {[
                "Your knowledge graph is yours — it updates in real time based on your actual performance, not just what you've clicked through.",
                "Three distinct teaching modes mean you're never locked into one way of learning.",
                "Study rooms let you learn alongside classmates and see how your mastery compares — anonymously and collaboratively.",
                "Everything from syllabus tracking to exam study guides is powered by Gemini, so the busywork of getting organized is handled for you.",
              ].map((item, i) => (
                <li key={i} className="flex gap-3">
                  <span className="text-green-600 mt-0.5">•</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>

          <p>
            Sapling is actively developed and we're always building. If something's broken or you have an idea, there's a feedback button in the navbar — we actually read those.
          </p>
        </div>

        <div className="mt-12 pt-8 border-t border-gray-200 text-sm text-gray-400">
          Built by Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez © 2026
        </div>
      </div>

      <footer className="border-t border-gray-200 bg-[#E9EFED] py-8 px-8">
        <div className="max-w-3xl mx-auto flex flex-wrap justify-center gap-6 text-sm text-gray-500">
          <Link href="/about" className="hover:text-gray-900 transition-colors">About</Link>
          <Link href="/terms" className="hover:text-gray-900 transition-colors">Terms of Service</Link>
          <Link href="/privacy" className="hover:text-gray-900 transition-colors">Privacy Policy</Link>
        </div>
      </footer>
    </div>
  );
}
