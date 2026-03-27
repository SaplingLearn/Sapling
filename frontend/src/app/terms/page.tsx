import Link from "next/link";

const sections = [
  {
    title: "1. Eligibility",
    body: "Sapling is intended for use by students and individuals for personal educational purposes. By using the Service, you represent that you are at least 13 years of age. If you are under 18, you should have parental or guardian consent.",
  },
  {
    title: "2. Your Account",
    body: "You are responsible for maintaining the confidentiality of your account credentials. You agree not to share your account with others or use another person's account. You are responsible for all activity that occurs under your account.",
  },
  {
    title: "3. Acceptable Use",
    body: "You agree to use Sapling only for lawful, educational purposes. You may not:",
    list: [
      "Upload content you do not have the right to share (e.g., copyrighted course materials you are not permitted to distribute)",
      "Attempt to reverse-engineer, scrape, or abuse the Service's APIs",
      "Use the Service to harass, impersonate, or harm other users",
      "Attempt to circumvent any security or authentication measures",
    ],
  },
  {
    title: "4. User Content",
    body: "You retain ownership of any content you upload, including documents, syllabi, and notes. By uploading content to Sapling, you grant us a limited license to process and analyze that content solely for the purpose of providing the Service to you. We do not use your uploaded materials to train AI models.",
  },
  {
    title: "5. AI-Generated Content",
    body: "Sapling uses Google Gemini to generate tutoring responses, quizzes, flashcards, and study guides. AI-generated content may occasionally be inaccurate or incomplete. You should not rely on it as a substitute for official course materials, instructors, or academic advisors. We make no guarantees about the accuracy of AI outputs.",
  },
  {
    title: "6. Study Rooms and Social Features",
    body: "Study rooms are shared spaces. You are responsible for the messages you send and the conduct you engage in within rooms. We reserve the right to remove users who violate these terms.",
  },
  {
    title: "7. Intellectual Property",
    body: "Sapling's software, branding, and design are the intellectual property of the Sapling team. You may not copy, reproduce, or distribute any part of the Service without explicit permission.",
  },
  {
    title: "8. Termination",
    body: "We reserve the right to suspend or terminate your access to Sapling at any time, for any reason, including violation of these Terms.",
  },
  {
    title: "9. Disclaimer of Warranties",
    body: 'The Service is provided "as is" without warranties of any kind. We do not guarantee uninterrupted access, error-free operation, or that the Service will meet your specific academic needs.',
  },
  {
    title: "10. Limitation of Liability",
    body: "To the fullest extent permitted by law, the Sapling team shall not be liable for any indirect, incidental, or consequential damages arising from your use of the Service.",
  },
  {
    title: "11. Changes to These Terms",
    body: "We may update these Terms from time to time. Continued use of the Service after changes are posted constitutes acceptance of the revised Terms.",
  },
  {
    title: "12. Contact",
    body: "For questions about these Terms, please email us at ",
    link: { label: "careers@saplinglearn.com", href: "mailto:careers@saplinglearn.com" },
  },
];

export default function TermsPage() {
  return (
    <div className="min-h-screen bg-[#F4F7F5] flex flex-col">
      <div className="flex-1 max-w-3xl mx-auto px-8 py-16 w-full">
        <div className="flex items-center gap-2 mb-12">
          <Link href="/" className="text-sm text-gray-500 hover:text-gray-900 transition-colors">
            ← Back to Sapling
          </Link>
        </div>

        <h1 className="text-4xl font-semibold text-gray-900 mb-2">Terms of Service</h1>
        <p className="text-sm text-gray-400 mb-10">Last updated: March 27, 2026</p>

        <p className="text-gray-600 leading-relaxed mb-10">
          By accessing or using Sapling ("the Service"), you agree to be bound by these Terms of Service. If you do not agree, please do not use the Service.
        </p>

        <div className="space-y-8">
          {sections.map((section) => (
            <div key={section.title}>
              <h2 className="text-base font-semibold text-gray-900 mb-2">{section.title}</h2>
              <p className="text-gray-600 leading-relaxed">
                {section.body}
                {section.link && (
                  <a href={section.link.href} className="text-green-700 hover:underline">{section.link.label}</a>
                )}
              </p>
              {section.list && (
                <ul className="mt-3 space-y-1.5 pl-4">
                  {section.list.map((item, i) => (
                    <li key={i} className="flex gap-2 text-gray-600">
                      <span className="text-gray-400 mt-0.5">•</span>
                      <span>{item}</span>
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
