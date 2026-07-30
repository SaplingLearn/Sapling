import type { Metadata } from 'next';
import CareersList from './CareersList';

// Server wrapper so the page can export metadata (#171); the interactive
// expanding job list stays a client child (CareersList).
export const metadata: Metadata = {
  title: 'Careers',
  description:
    "Join the small team building Sapling — AI-powered study tools that help students learn better. See open roles across engineering and growth.",
  alternates: { canonical: '/careers' },
};

export default function CareersPage() {
  return <CareersList />;
}
