import Link from "next/link";

const sections = [
  {
    title: "1. Information We Collect",
    subsections: [
      {
        label: "Information you provide directly:",
        list: [
          "Account information (name, email address) via Google OAuth sign-in",
          "Course names, syllabus text, and assignment information you paste or upload",
          "Documents and PDFs you upload to your document library",
          "Messages sent in study room chats",
          "Feedback and bug reports you submit",
        ],
      },
      {
        label: "Information generated through your use of the Service:",
        list: [
          "Knowledge graph data (concepts studied, mastery scores, session history)",
          "Quiz responses and performance data",
          "Flashcard ratings and review history",
          "Tutoring session transcripts",
        ],
      },
      {
        label: "Information collected automatically:",
        list: [
          "Basic usage data and session metadata to maintain and improve the Service",
        ],
      },
    ],
  },
  {
    title: "2. How We Use Your Information",
    body: "We use the information we collect to:",
    list: [
      "Provide and personalize the Service, including updating your knowledge graph and generating AI content tailored to your performance",
      "Enable study room and social features, including anonymized class-wide insights",
      "Process and respond to feedback and issue reports",
      "Maintain the security and integrity of the Service",
    ],
  },
  {
    title: "3. Google OAuth and Calendar",
    body: "If you sign in with Google or connect your Google Calendar, we receive access tokens to authenticate you and, if you grant calendar access, to read and write assignment data. We do not access any Google data beyond what is necessary to provide the features you enable. You can revoke this access at any time through your Google account settings.",
  },
  {
    title: "4. How We Share Your Information",
    body: "We do not sell your personal data. We share information only in the following limited circumstances:",
    highlights: [
      { label: "Service providers:", text: "We use Supabase (database), Google Gemini (AI processing), and similar infrastructure providers. These providers process data on our behalf under their own privacy policies." },
      { label: "Study rooms:", text: "Your display name, avatar, and knowledge graph data are visible to other members of study rooms you join. Class-wide data shared with other users is anonymized." },
      { label: "Legal requirements:", text: "We may disclose information if required by law or to protect the rights and safety of our users." },
    ],
  },
  {
    title: "5. Data Retention",
    body: "We retain your data for as long as your account is active. You may request deletion of your account and associated data by submitting a request through the app's feedback tool.",
  },
  {
    title: "6. Security",
    body: "We take reasonable technical measures to protect your data, including encrypted connections and access-controlled database infrastructure via Supabase. No system is completely secure, and we cannot guarantee absolute security.",
  },
  {
    title: "7. Children's Privacy",
    body: "Sapling is not directed at children under 13. We do not knowingly collect personal information from children under 13. If you believe a child under 13 has provided us with personal data, please email us at ",
    link: { label: "careers@saplinglearn.com", href: "mailto:careers@saplinglearn.com" },
    bodySuffix: " and we will take steps to delete it.",
  },
  {
    title: "8. Changes to This Policy",
    body: "We may update this Privacy Policy from time to time. We will notify users of material changes by updating the date at the top of this page.",
  },
  {
    title: "9. Contact",
    body: "If you have questions or concerns about this Privacy Policy, please email us at ",
    link: { label: "careers@saplinglearn.com", href: "mailto:careers@saplinglearn.com" },
    bodySuffix: ".",
  },
];

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-[#F4F7F5] flex flex-col">
      <div className="flex-1 max-w-3xl mx-auto px-8 py-16 w-full">
        <div className="flex items-center gap-2 mb-12">
          <Link href="/" className="text-sm text-gray-500 hover:text-gray-900 transition-colors">
            ← Back to Sapling
          </Link>
        </div>

        <h1 className="text-4xl font-semibold text-gray-900 mb-2">Privacy Policy</h1>
        <p className="text-sm text-gray-400 mb-10">Last updated: March 27, 2026</p>

        <p className="text-gray-600 leading-relaxed mb-10">
          This Privacy Policy explains how Sapling ("we," "us," or "our") collects, uses, and protects your information when you use our Service.
        </p>

        <div className="space-y-8">
          {sections.map((section) => (
            <div key={section.title}>
              <h2 className="text-base font-semibold text-gray-900 mb-2">{section.title}</h2>

              {section.body && (
                <p className="text-gray-600 leading-relaxed mb-3">
                  {section.body}
                  {section.link && (
                    <a href={section.link.href} className="text-green-700 hover:underline">{section.link.label}</a>
                  )}
                  {section.bodySuffix}
                </p>
              )}

              {section.list && (
                <ul className="space-y-1.5 pl-4">
                  {section.list.map((item, i) => (
                    <li key={i} className="flex gap-2 text-gray-600">
                      <span className="text-gray-400 mt-0.5">•</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              )}

              {section.subsections && (
                <div className="space-y-4">
                  {section.subsections.map((sub) => (
                    <div key={sub.label}>
                      <p className="text-sm font-medium text-gray-700 mb-1.5">{sub.label}</p>
                      <ul className="space-y-1.5 pl-4">
                        {sub.list.map((item, i) => (
                          <li key={i} className="flex gap-2 text-gray-600">
                            <span className="text-gray-400 mt-0.5">•</span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}

              {section.highlights && (
                <ul className="space-y-2 pl-4">
                  {section.highlights.map((h) => (
                    <li key={h.label} className="flex gap-2 text-gray-600">
                      <span className="text-gray-400 mt-0.5">•</span>
                      <span>
                        <strong className="text-gray-800">{h.label}</strong> {h.text}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>

        <div className="mt-12 pt-8 border-t border-gray-200 text-sm text-gray-400">
          © 2026 Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez. All Rights Reserved.
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
