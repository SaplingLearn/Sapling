import { useId, type ReactNode } from "react";
import type { QuizQuestionContext } from "@/lib/quiz/types";
import { QuizMath } from "./QuizMath";
import "./problemContext.css";

type Graph = NonNullable<QuizQuestionContext["graph"]>;

function QuestionGraph({ graph }: { graph: Graph }) {
  const titleId = useId();
  const { points, x_label, y_label } = graph;
  const xMin = points[0][0];
  const xMax = points[points.length - 1][0];
  const ys = points.map(([, y]) => y);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const yPadding = yMax === yMin ? Math.max(1, Math.abs(yMin) * 0.1) : (yMax - yMin) * 0.1;
  const xPixel = (x: number) => 65 + (x - xMin) / (xMax - xMin) * 385;
  const yPixel = (y: number) => 166 - (y - yMin + yPadding) / (yMax - yMin + 2 * yPadding) * 146;
  const formatTick = (value: number) => Number(value.toPrecision(4)).toString();
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <figure className="quiz-problem-graph">
      <svg viewBox="0 0 480 218" role="img" aria-labelledby={titleId}>
        <title id={titleId}>{y_label} by {x_label}</title>
        {ticks.map(fraction => {
          const x = xMin + fraction * (xMax - xMin);
          const y = yMin === yMax ? yMin + (fraction - 0.5) * yPadding : yMin + fraction * (yMax - yMin);
          return (
            <g key={fraction}>
              <path className="quiz-problem-graph__grid" d={`M${xPixel(x)} 20V166 M65 ${yPixel(y)}H450`} />
              <text x={xPixel(x)} y="183" textAnchor="middle">{formatTick(x)}</text>
              <text x="59" y={yPixel(y)} dominantBaseline="middle" textAnchor="end">{formatTick(y)}</text>
            </g>
          );
        })}
        <path className="quiz-problem-graph__axes" d="M65 20V166H450" />
        <polyline className="quiz-problem-graph__line" points={points.map(([x, y]) => `${xPixel(x)},${yPixel(y)}`).join(" ")} />
        {points.map(([x, y]) => <circle key={x} cx={xPixel(x)} cy={yPixel(y)} r="3" />)}
        <text x="258" y="209" textAnchor="middle">{x_label}</text>
        <text transform="translate(13 93) rotate(-90)" textAnchor="middle">{y_label}</text>
      </svg>
    </figure>
  );
}

export function QuizProblemContext({ context, children }: { context: QuizQuestionContext; children?: ReactNode }) {
  return (
    <div className="quiz-problem-context">
      {context.parts > 1 && <p>Part {context.part} of {context.parts} · 1 point</p>}
      <p><QuizMath text={context.stem} /></p>
      {children}
      {context.graph && <QuestionGraph graph={context.graph} />}
    </div>
  );
}
