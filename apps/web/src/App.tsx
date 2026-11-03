import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { MotionConfig } from "motion/react";
import { Shell } from "./app/Shell";
import { EvalPage } from "./features/eval/EvalPage";
import { HomePage } from "./features/home/HomePage";
import { ReaderPage } from "./features/reader/ReaderPage";
import { CourseDetailPage, LibraryPage } from "./features/library";
import { StudioPage } from "./features/studio/StudioPage";

/** 路由(甲方案·五区制):列表页有壳(Shell),阅读器沉浸(不套壳)
 *  / 学习台(继续学+推荐) /courses 课程库+详情 /studio 生成中心 /eval 观测
 *  /read/:id 书页阅读器(P6 起为唯一课堂形态,幻灯片已退役) */
const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "courses", element: <LibraryPage /> },
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
