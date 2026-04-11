import { Link } from "react-router-dom";
import { motion, useInView } from "framer-motion";
import { useRef } from "react";
import { Sparkles, MessageSquare, FileDown } from "lucide-react";
import { Button } from "@/components/ui/button";

const features = [
  {
    icon: Sparkles,
    title: "AI-Powered Cleaning",
    description: "Detect and fix missing values, duplicates, type mismatches, and formatting issues automatically.",
  },
  {
    icon: MessageSquare,
    title: "Natural Language Analysis",
    description: "Ask questions about your data in plain English. Get charts, summaries, and insights instantly.",
  },
  {
    icon: FileDown,
    title: "Export Anywhere",
    description: "Download your cleaned data as CSV, Excel, JSON, or Parquet with one click.",
  },
] as const;

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.12 } },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: "easeOut" as const } },
};

export default function Landing() {
  const featuresRef = useRef<HTMLDivElement>(null);
  const featuresInView = useInView(featuresRef, { once: true, amount: 0.2 });

  return (
    <div className="min-h-screen bg-[var(--surface-canvas)] font-sans">
      <header className="border-b border-[var(--line)]">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
          <span className="text-[15px] font-bold tracking-tight text-brand-600">DataPilot</span>
          <Link to="/app/upload">
            <Button size="sm" className="bg-brand-600 text-white hover:bg-brand-700">
              Open App
            </Button>
          </Link>
        </div>
      </header>

      <section className="mx-auto max-w-3xl px-4 py-24 text-center">
        <h1 className="text-4xl font-bold leading-tight tracking-tight text-ink md:text-5xl">
          Your data, finally clean.
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-[15px] leading-relaxed text-ink-secondary">
          Upload messy spreadsheets. Get clean data, smart insights, and
          polished exports&nbsp;&mdash; powered by AI.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link to="/app/upload">
            <Button className="bg-brand-600 text-white hover:bg-brand-700">Upload a file</Button>
          </Link>
          <Link to="/app/dashboard">
            <Button variant="outline">Go to Dashboard</Button>
          </Link>
        </div>
      </section>

      <section className="border-t border-[var(--line)] py-20" ref={featuresRef}>
        <div className="mx-auto max-w-5xl px-4">
          <motion.div
            className="grid gap-6 md:grid-cols-3"
            variants={containerVariants}
            initial="hidden"
            animate={featuresInView ? "visible" : "hidden"}
          >
            {features.map((f) => (
              <motion.div
                key={f.title}
                variants={itemVariants}
                className="rounded-lg border border-[var(--line)] bg-[var(--surface-primary)] p-5"
              >
                <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50">
                  <f.icon className="h-[18px] w-[18px] text-brand-600" />
                </div>
                <h3 className="text-sm font-semibold text-ink">{f.title}</h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-ink-tertiary">
                  {f.description}
                </p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      <footer className="border-t border-[var(--line)] py-8">
        <div className="mx-auto flex max-w-5xl items-center justify-center gap-3 px-4 text-xs text-ink-muted">
          <span className="font-bold text-brand-600">DataPilot</span>
          <span>&middot;</span>
          <span>&copy; {new Date().getFullYear()}</span>
        </div>
      </footer>
    </div>
  );
}
