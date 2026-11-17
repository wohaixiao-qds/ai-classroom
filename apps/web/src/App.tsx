import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { MotionConfig } from "motion/react";
import { Shell } from "./app/Shell";
import { EvalPage } from "./features/eval/EvalPage";
import { ReaderPage } from "./features/reader/ReaderPage";
import { BookPage, CourseDetailPage, LibraryPage } from "./features/library";
import { StudioPage } from "./features/studio/StudioPage";

/** 路由(IA 合一 2026-11-17):学习台退役,/ 重定向到学习页(/courses)。
 *  /courses 学习(书架+今日横条) /books/:topic 书页目录 /courses/:id 详情
 *  /studio 生成中心 /eval 观测;/read/:id 书页阅读器沉浸不套壳 */
const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <Navigate to="/courses" replace /> },
      { path: "courses", element: <LibraryPage /> },
      { path: "books/:topic", element: <BookPage /> },
      { path: "courses/:courseId", element: <CourseDetailPage /> },
      { path: "studio", element: <StudioPage /> },
      { path: "eval", element: <EvalPage /> },
    ],
  },
  { path: "/read/:courseId", element: <ReaderPage /> },
]);

export default function App() {
  return (
    /* 动效全局开关:用户系统开了「减少动态效果」时,motion 自动跳过非必要动画 */
    <MotionConfig reducedMotion="user">
      <RouterProvider router={router} />
    </MotionConfig>
  );
}
