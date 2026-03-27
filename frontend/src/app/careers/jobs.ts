export interface Job {
  id: number;
  slug: string;
  title: string;
  department: string;
  location: string;
  type: string;
  description: string;
  tags: string[];
}

export const JOBS: Job[] = [
  {
    id: 1,
    slug: 'marketing-intern',
    title: 'Marketing Intern',
    department: 'Growth',
    location: 'Hybrid',
    type: 'Internship',
    description:
      "Help Sapling reach more students. You'll run social campaigns, create content, build relationships with student organizations, and help shape our brand voice from the ground up. Great fit for someone who loves learning and wants real ownership from day one.",
    tags: ['Branding', 'Content Creation', 'Social Media', 'Community', 'Analytics', 'AI Fluency'],
  },
];

export const DEPT_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  Growth: { bg: 'rgba(217,119,6,0.07)', text: '#b45309', border: 'rgba(217,119,6,0.18)' },
};
