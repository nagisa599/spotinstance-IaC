# Presentation Script: A Time-of-Day-Aware Empirical Study of AWS Spot Instance Reliability for Short-Running Workloads

Target time: about 15 minutes (a time guide is written for each slide)
Note: This is a speaking script. Please change the wording to fit your own style.

---

## Slide 1: Title (about 0:40)

Hello, everyone. Today I will talk about "A Time-of-Day-Aware Empirical Study of AWS Spot Instance Reliability for Short-Running Workloads." My name is Nagisa Nasu, from Doshisha University. Thank you very much.

In this study, we look at the reliability of AWS spot instances from the point of view of "time of day." We focus on short-running workloads, such as CI/CD and batch processing, which finish in a few minutes to about one hour. In this talk, I will explain why time of day matters, what metric we define for it, and what we learned from real measurements.

---

## Slide 2: Background — Spot Instances and Cost Saving (about 1:10)

First, the background. In recent years, cloud computing is widely used by companies, research institutions, and individual developers. As usage grows, and the demand for high-performance resources increases, the cost of cloud computing has become an important problem for many users.

One common way to reduce this cost is to use "spot instances." Spot instances are a pricing model. Cloud providers offer their spare computing resources, which are not being used, at a lower price than on-demand instances. The discount is from several tens of percent up to about 90 percent.

Because they are cheap, spot instances are used not only for large jobs like machine learning and batch processing, but also for workloads that need computing power for only a short time, such as automated build and test in CI/CD.

---

## Slide 3: Problem — Interruption Events (about 1:05)

However, because spot instances use "spare capacity," they have a big weakness. When the total cloud demand goes up, or the free capacity goes down, a running instance can be stopped by force, for the provider's own reasons. This is called an "interruption event."

The problem happens when an interruption occurs while a workload is running. Batch processing, machine learning, and CI/CD build and test often have to start again from the beginning if they are stopped in the middle. As a result, both the execution time and the cloud cost go up, and the benefit of the low price is cancelled out.

So, spot instances are good for saving cost, but their reliability strongly depends on interruption events. This is the basic problem.

---

## Slide 4: Existing Methods and Their Limits — SPS (about 1:20)

Several approaches have been proposed for this interruption risk. Typical ones are bidding strategies that consider price changes, and the Spot Placement Score, or SPS, provided by AWS. SPS tells you how likely a spot request can be fulfilled, when you specify conditions such as instance type, region, and required capacity. In other words, it estimates whether you can launch the instance.

Here is the important difference that this study starts from. "Being able to launch" and "being able to keep running until the workload finishes" are two completely different things. Even if the launch succeeds, if the instance is interrupted before the job finishes, the short-running workload ends in failure.

SPS and survival time show launch-time availability, or infrastructure-level survival time. They do not directly tell you whether the instance will stay alive until a specific workload deadline. For users of short workloads, the second one is what they really want to know, and that is exactly the limit of the existing indicators.

---

## Slide 5: Goal and Novelty of This Study (about 1:10)

So in this study, we actively treat "time of day" not as a feature of the spot market, but as an operational variable to decide "when to run a short-running workload."

We redefine spot instance reliability. Instead of launch availability or infrastructure-level survival time, we use "deadline-conditioned completion feasibility."

Our main contributions are these four points.
First, we redefine reliability for short workloads as completion feasibility, not launch availability.
Second, we treat time of day as an operational scheduling factor, and analyze its effect.
Third, we build an AWS-based measurement framework that records launch success and post-launch interruption separately.
And fourth, we do a preliminary empirical study, using deadlines of 5, 10, 30, and 60 minutes.

---

## Slide 6: Proposed Metric — Definition of F_comp(d) (about 1:20)

Now let me define our metric.

First, let N_req be the total number of launch requests, and N_succ be the number of instances that launched successfully.
The launch success rate, R_launch, is N_succ divided by N_req. This shows launch-time availability.

Next, let N_int(d) be the number of successfully launched instances that were interrupted before deadline d.
Then the interruption rate, R_int(d), is N_int(d) divided by N_succ.

And the key metric of this study, the completion feasibility F_comp(d), is one minus the interruption rate. This means the fraction of successfully launched instances that survived, without interruption, until deadline d.

For d, we use four values: 5, 10, 30, and 60 minutes. We match these to the typical run time of short CI/CD jobs, tests, and batch processing. Please note that this metric does not measure the real success rate of an application. It is a proxy for completion feasibility, based on instance survival.

---

## Slide 7: Measurement Framework (about 1:15)
(Figure: Proposed measurement framework / images/artect.png)

This is our proposed measurement framework.

First, a scheduler sends spot instance launch requests at regular intervals, for each target instance type. Then, each instance that launches successfully is observed for a fixed period of one hour.

During this observation window, the system records three things: whether the request was fulfilled, how long the instance stayed available, and whether an interruption event happened before the scheduled end. If no interruption happens within one hour, the system terminates the instance itself.

In our implementation, a scheduler-driven Lambda function launches spot instances periodically, and records the launch result, runtime status, and interruption events into a database. The most important point here is that we record launch success and post-launch interruption separately. This lets us clearly tell apart "failure due to lack of capacity at launch time" and "interruption after launch."

---

## Slide 8: Experimental Setup (about 1:10)

Next is our experimental setup.

For instance types, we chose three types with different characteristics: c6a.large, which is compute-oriented; g4dn.xlarge, which is GPU-based; and t3.micro, which is lightweight. Our aim is to compare interruption trends across types with different resource characteristics.

For regions, we used four: N. Virginia, Tokyo, Ireland, and Singapore. For each region and each instance type, we launched one spot instance every hour.

For the time-of-day analysis, we normalized the timestamps to the local time of each region, and split one day into four periods of six hours each. Night is 0 to 6, Morning is 6 to 12, Afternoon is 12 to 18, and Evening is 18 to 24. This lets us compare based on the demand cycle of each region.

The experiment ran for one week, from May 19 to May 25, 2026. We did not set a maximum spot price, so we observed the behavior under the default AWS setting.

---

## Slide 9: Overview of Results (about 1:05)
(Figure: Figure 1 / F_comp(60) heatmap)

Now the results. During the observation period, we sent 2,016 launch requests in total, across four regions and three types. Of these, 1,950 instances launched successfully. The overall launch success rate was 96.7 percent. Among the successfully launched instances, 117, or 6.0 percent, were interrupted before the end of the one-hour window.

This heatmap shows F_comp(60), the 60-minute completion feasibility, for each time period, region, and instance type.

First, please look at t3.micro. In all regions and all time periods, its F_comp(60) was 0.95 or higher. So the lightweight instance is robust to interruption, regardless of timing. On the other hand, c6a.large and g4dn.xlarge changed a lot by time of day, over a wide range from about 0.65 to 1.00. So for compute-oriented and GPU types, time of day becomes a more important factor in practice.

---

## Slide 10: Results — Effect of Time of Day (about 1:30)
(Figure: Figure 2 / F_comp(d) for four region-type combinations)

Next, let me look in detail at the four combinations with the largest change by time of day, for each deadline. The x-axis is the deadline, and each line is a time period.

First, in panel (a), N. Virginia c6a.large, the Night period was 0.98, but the Morning period dropped to 0.69. The difference is about 0.29. The two 95-percent confidence intervals do not overlap, so this difference is hard to explain by random sampling. Also, even at the shortest deadline of 5 minutes, Morning was already 0.90. This means interruption risk starts to build up within only the first five minutes.

In panel (b), Ireland c6a.large, we see the same trend: Night 1.00, Morning 0.73, and Afternoon 0.88.

In panel (c), Tokyo g4dn.xlarge, Morning was the lowest at 0.77, while Night and Evening were high, from 0.97 to 1.00.

In panel (d), Singapore, Afternoon was the lowest at 0.78.

Across all four panels, Night was always the highest, or close to the highest. And the riskiest period was Morning or Afternoon, and it changed depending on the region. This is preliminary evidence that time of day can be a meaningful signal for scheduling.

---

## Slide 11: Discussion — Time of Day and Instance Type (about 1:15)

Now the discussion.

The pattern we observed matches well with the hypothesis that cloud demand follows a daily cycle. During local night hours, business demand is lower, so there is more spare capacity for spot instances. In contrast, Morning and Afternoon match the start of local business hours, so competition in the spot market and interruption rates go up. In fact, the riskiest period changes by region, and this also supports our interpretation. For N. Virginia, Ireland, and Tokyo, Morning is the riskiest; for Singapore, Afternoon is. These match the business peaks of North America and Europe, and of Asia.

We can also discuss the instance type. Lightweight burstable types like t3.micro have less competition for spare capacity, so they are stable. But compute-optimized and GPU types have high demand from machine learning and batch jobs, so competition is strong. This matches the finding of Lee and colleagues in SpotLake, that GPU and large instances have lower availability. Our study extends that finding to a deadline-conditioned view, that is, its dependence on time of day.

---

## Slide 12: Implications for Workload Scheduling (about 1:10)

Next, the implications for practice.

When you use c6a.large or g4dn.xlarge in regions like N. Virginia, Ireland, or Tokyo, just running CI/CD or batch jobs in the Night period can improve F_comp(60) by up to 0.29, compared to Morning. And this method does not need any change to the workload itself, or any provider-specific API call.

F_comp(d) can be computed only from directly observed launch and interruption records. So it is a transparent and easy-to-understand scheduling signal. But it is not a replacement for SPS. They are complementary: SPS handles launch-time placement, and F_comp handles post-launch continuity. So using both together should be helpful for the user.

Also, even when you cannot move the deadline time, you can use region selection: send the job to a region where it is currently nighttime. This uses the low interruption rate of the Night period, without delaying the execution.

---

## Slide 13: Limitations and Future Work (about 0:50)

Let me also mention the limitations. First, the observation period was only one week, and the sample per time period was about 30 to 42. So we cannot generalize to long-term or seasonal trends. Second, we did not run real applications; we used instance survival as a proxy for completion feasibility. Third, we launched only one instance per hour, so we did not capture the effect of concurrent launches or queue behavior. Fourth, we did not set a maximum price, so we only saw the behavior under the default setting.

Now, our future work. In this study, through the measurement of F_comp(d), we were able to build a scheduling strategy for spot instances that considers time of day and region. As the next step, we want to implement this strategy as a function. The idea is to "functionalize" it, so that when you give the time of day, the region, and the instance type as input, it returns the execution conditions with high completion feasibility. Then, instead of using instance survival as a proxy, we want to run real workloads, such as actual CI/CD and batch processing, and evaluate whether this strategy really improves the completion rate and the cost. In addition, we will extend the observation period, increase the sampling frequency, and compare F_comp with existing indicators such as SPS.

---

## Slide 14: Conclusion (about 0:50)

Finally, let me conclude. In this study, we defined a time-of-day-aware metric, F_comp(d), and measured it across four regions and three instance types.

This metric does not capture launch-time availability or infrastructure-level survival time. Instead, it captures post-launch continuity until a workload-specific deadline, from 5 to 60 minutes.

And the main idea is to treat time of day as an operational variable, to decide when to run short workloads. As a result, we showed, based on real measurements, that by choosing the Night period, or by choosing a region, you can lower the interruption risk without extra cost or extra API calls.

That is all for my presentation. Thank you very much for your attention.
